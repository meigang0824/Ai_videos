from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _strip_slashes(value: str) -> str:
    return value.strip().strip("/")


def _object_key(*parts: str) -> str:
    cleaned = [_strip_slashes(part) for part in parts if part and _strip_slashes(part)]
    return "/".join(cleaned)


def _normalize_endpoint(value: str) -> str:
    value = value.strip()
    if value and not value.startswith(("http://", "https://")):
        return f"https://{value}"
    return value


class ObjectStorage:
    def __init__(self):
        self.provider = os.getenv("OBJECT_STORAGE_PROVIDER", "local").strip().lower()
        self.endpoint = _normalize_endpoint(os.getenv("ALIYUN_OSS_ENDPOINT", ""))
        self.bucket_name = os.getenv("ALIYUN_OSS_BUCKET", "").strip()
        self.access_key_id = os.getenv("ALIYUN_OSS_ACCESS_KEY_ID", "").strip()
        self.access_key_secret = os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "").strip()
        self.prefix = _strip_slashes(os.getenv("ALIYUN_OSS_PREFIX", "cosyvoice").strip())
        self.public_base_url = os.getenv("ALIYUN_OSS_PUBLIC_BASE_URL", "").strip().rstrip("/")
        try:
            self.signed_url_ttl = max(60, int(os.getenv("ALIYUN_OSS_SIGNED_URL_TTL", "3600")))
        except ValueError:
            self.signed_url_ttl = 3600
        self._bucket = None
        self._error = ""

    def enabled(self) -> bool:
        return self.provider in {"aliyun_oss", "oss"} and all(
            [self.endpoint, self.bucket_name, self.access_key_id, self.access_key_secret]
        )

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled(),
            "configured": self.provider in {"aliyun_oss", "oss"},
            "bucket": self.bucket_name,
            "endpoint": self.endpoint,
            "prefix": self.prefix,
            "last_error": self._error,
        }

    def key(self, user_id: str, purpose: str, filename: str, task_id: str | None = None) -> str:
        if task_id:
            return _object_key(self.prefix, "users", user_id, purpose, task_id, filename)
        return _object_key(self.prefix, "users", user_id, purpose, filename)

    def upload_file(self, local_path: Path, key: str, content_type: str | None = None) -> dict[str, Any] | None:
        if not self.enabled() or not local_path.exists():
            return None
        bucket = self._get_bucket()
        headers = {"Content-Type": content_type} if content_type else None
        bucket.put_object_from_file(key, str(local_path), headers=headers)
        return {"provider": "aliyun_oss", "key": key, "url": self.url_for(key)}

    def upload_fileobj(self, fileobj: Any, key: str, content_type: str | None = None) -> dict[str, Any] | None:
        if not self.enabled():
            return None
        bucket = self._get_bucket()
        headers = {"Content-Type": content_type} if content_type else None
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)
        bucket.put_object(key, fileobj, headers=headers)
        return {"provider": "aliyun_oss", "key": key, "url": self.url_for(key)}

    def delete_object(self, key: str | None) -> bool:
        key = (key or "").strip()
        if not key or not self.enabled():
            return False
        bucket = self._get_bucket()
        bucket.delete_object(key)
        return True

    def url_for(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{key.lstrip('/')}"
        return ""

    def signed_url(self, key: str, method: str = "GET", expires: int | None = None) -> str:
        if not self.enabled():
            return ""
        bucket = self._get_bucket()
        return bucket.sign_url(method, key, expires or self.signed_url_ttl, slash_safe=True)

    def _get_bucket(self):
        if self._bucket is not None:
            return self._bucket
        try:
            import oss2
        except ImportError as exc:
            self._error = "oss2 SDK 未安装"
            raise RuntimeError(self._error) from exc
        auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
        return self._bucket


object_storage = ObjectStorage()
