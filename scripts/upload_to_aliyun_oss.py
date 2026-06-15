#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = [
    BASE_DIR / "backend" / "storage" / "uploads",
    BASE_DIR / "outputs",
    BASE_DIR / "voices",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload local media/runtime files to Aliyun OSS.")
    parser.add_argument("--root", action="append", dest="roots", help="Directory or file to upload. Can be repeated.")
    parser.add_argument("--user-id", default="local", help="Object key user segment.")
    parser.add_argument(
        "--purpose",
        default=f"bulk/{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        help="Object key purpose segment.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned uploads without sending files.")
    parser.add_argument("--include-urls", action="store_true", help="Include returned object URLs in output.")
    return parser.parse_args()


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {".DS_Store"}:
            continue
        yield path


def relative_name(path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            rel = path.relative_to(root if root.is_dir() else root.parent)
            return f"{root.name}/{rel.as_posix()}" if root.is_dir() else rel.as_posix()
        except ValueError:
            continue
    return path.name


def main() -> int:
    args = parse_args()
    os.environ.setdefault("OBJECT_STORAGE_PROVIDER", "aliyun_oss")

    sys.path.insert(0, str(BASE_DIR))
    from pipeline.object_storage import object_storage

    if not object_storage.enabled() and not args.dry_run:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "Aliyun OSS is not configured. Set ALIYUN_OSS_ENDPOINT, ALIYUN_OSS_BUCKET, ALIYUN_OSS_ACCESS_KEY_ID, and ALIYUN_OSS_ACCESS_KEY_SECRET.",
                    "status": object_storage.status(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    roots = [Path(item).expanduser().resolve() for item in (args.roots or [str(p) for p in DEFAULT_ROOTS])]
    uploaded = []
    skipped = []
    failed = []

    for root in roots:
        for path in iter_files(root):
            rel = relative_name(path, roots)
            key = object_storage.key(args.user_id, args.purpose, rel)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if args.dry_run:
                skipped.append({"path": str(path), "key": key, "bytes": path.stat().st_size})
                continue
            try:
                result = object_storage.upload_file(path, key, content_type=content_type)
                item = {"path": str(path), "key": key, "bytes": path.stat().st_size}
                if args.include_urls:
                    item["url"] = (result or {}).get("url")
                uploaded.append(item)
            except Exception as exc:
                failed.append({"path": str(path), "key": key, "error": str(exc)})

    print(
        json.dumps(
            {
                "ok": not failed,
                "status": object_storage.status(),
                "uploaded_count": len(uploaded),
                "skipped_count": len(skipped),
                "failed_count": len(failed),
                "uploaded_bytes": sum(item["bytes"] for item in uploaded),
                "dry_run": args.dry_run,
                "uploaded": uploaded[:200],
                "skipped": skipped[:200],
                "failed": failed[:50],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
