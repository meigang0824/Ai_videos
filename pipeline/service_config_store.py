from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from pipeline.config import STORAGE_DIR
from pipeline.database import create_app_engine, ensure_schema, service_configs_table


SERVICE_CONFIG_DB_PATH = STORAGE_DIR / "service_config.sqlite3"
DEFAULT_CONFIG_ID = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class ServiceConfigStore:
    def __init__(self, path: Path = SERVICE_CONFIG_DB_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.engine = create_app_engine(path)
        ensure_schema(self.engine)

    def load(self, config_id: str = DEFAULT_CONFIG_ID) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(service_configs_table.c.config_json).where(service_configs_table.c.id == config_id)
            ).first()
        return _json_load(row[0]) if row else None

    def save(self, config: dict[str, Any], config_id: str = DEFAULT_CONFIG_ID) -> dict[str, Any]:
        payload = dict(config)
        with self.lock, self.engine.begin() as conn:
            conn.execute(service_configs_table.delete().where(service_configs_table.c.id == config_id))
            conn.execute(
                service_configs_table.insert().values(
                    id=config_id,
                    config_json=_json_dump(payload),
                    updated_at=_now(),
                )
            )
        return payload

    def migrate_from_file(self, config_path: Path, config_id: str = DEFAULT_CONFIG_ID) -> dict[str, Any] | None:
        existing = self.load(config_id)
        if existing is not None:
            return existing
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return self.save(data, config_id=config_id)


service_config_store = ServiceConfigStore()
