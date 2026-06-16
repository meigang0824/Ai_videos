from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update

from pipeline.config import BASE_DIR, VOICE_DIR
from pipeline.database import create_app_engine, ensure_schema, voices_table


VOICE_DB_PATH = Path(BASE_DIR) / "backend" / "storage" / "voices.sqlite3"
LOCAL_USER_ID = "local"


def _mapping(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _clean_voice(item: dict[str, Any]) -> dict[str, Any]:
    voice_id = str(item.get("id") or "").strip()
    ref_wav = str(item.get("ref_wav") or "").strip()
    return {
        "id": voice_id,
        "user_id": str(item.get("user_id") or LOCAL_USER_ID),
        "name": str(item.get("name") or voice_id or "未命名音色"),
        "kind": str(item.get("kind") or "local"),
        "ref_wav": ref_wav,
        "ref_text": str(item.get("ref_text") or ""),
        "size_bytes": int(item.get("size_bytes") or 0),
        "storage_provider": str(item.get("storage_provider") or ""),
        "object_key": str(item.get("object_key") or ""),
        "object_url": str(item.get("object_url") or ""),
        "object_error": str(item.get("object_error") or ""),
        "meta_object_key": str(item.get("meta_object_key") or ""),
        "meta_object_url": str(item.get("meta_object_url") or ""),
        "meta_object_error": str(item.get("meta_object_error") or ""),
        "created_at": str(item.get("created_at") or ""),
    }


class VoiceStore:
    def __init__(self, path: Path = VOICE_DB_PATH, *, migrate: bool = True):
        self.path = path
        self.lock = threading.RLock()
        self.engine = create_app_engine(path)
        ensure_schema(self.engine)
        if migrate:
            self.migrate_json_dir()

    def migrate_json_dir(self, voice_dir: Path = VOICE_DIR) -> int:
        migrated = 0
        for meta_path in voice_dir.glob("*.json"):
            try:
                item = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(item, dict):
                continue
            item.setdefault("id", meta_path.name.removesuffix(".json"))
            item.setdefault("user_id", LOCAL_USER_ID)
            item.setdefault("kind", "local")
            if self.upsert_voice(item):
                migrated += 1
        return migrated

    def upsert_voice(self, item: dict[str, Any]) -> dict[str, Any] | None:
        voice = _clean_voice(item)
        if not voice["id"] or not voice["ref_wav"]:
            return None
        with self.lock, self.engine.begin() as conn:
            conn.execute(voices_table.delete().where(voices_table.c.id == voice["id"]))
            conn.execute(voices_table.insert().values(**voice))
        return voice

    def list_voices(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query = select(voices_table)
        if user_id:
            query = query.where(voices_table.c.user_id == user_id)
        query = query.order_by(voices_table.c.created_at.desc())
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [_mapping(row) for row in rows]

    def get_voice(self, voice_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        query = select(voices_table).where(voices_table.c.id == voice_id)
        if user_id:
            query = query.where(voices_table.c.user_id == user_id)
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(query).first()
        return _mapping(row) if row else None

    def get_voice_by_path(self, ref_wav: Path, user_id: str | None = None) -> dict[str, Any] | None:
        query = select(voices_table).where(voices_table.c.ref_wav == str(ref_wav))
        if user_id:
            query = query.where(voices_table.c.user_id == user_id)
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(query).first()
        return _mapping(row) if row else None

    def update_voice_name(self, voice_id: str, name: str, user_id: str | None = None) -> dict[str, Any] | None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return None
        query = update(voices_table).where(voices_table.c.id == voice_id).values(name=clean_name)
        if user_id:
            query = query.where(voices_table.c.user_id == user_id)
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(query)
        if result.rowcount < 1:
            return None
        return self.get_voice(voice_id, user_id=user_id)

    def delete_voice(self, voice_id: str, user_id: str | None = None) -> bool:
        query = delete(voices_table).where(voices_table.c.id == voice_id)
        if user_id:
            query = query.where(voices_table.c.user_id == user_id)
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(query)
        return result.rowcount > 0


voice_store = VoiceStore()
