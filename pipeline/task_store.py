from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select

from pipeline.config import BASE_DIR
from pipeline.database import create_app_engine, ensure_schema, tasks_table, uploads_table


STORAGE_DIR = Path(BASE_DIR) / "backend" / "storage"
LEGACY_TASK_STORE_PATH = STORAGE_DIR / "task_store.json"
TASK_STORE_DB_PATH = STORAGE_DIR / "task_store.sqlite3"
MAX_HISTORY_ITEMS = 200
LOCAL_USER_ID = "local"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _mapping(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _row_to_task(row: Any) -> dict[str, Any]:
    row = _mapping(row)
    return {
        "task_id": row["task_id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "title": row["title"],
        "status": row["status"],
        "progress": row["progress"],
        "message": row["message"],
        "payload": _json_load(row["payload_json"], {}),
        "result": _json_load(row["result_json"], None),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def _row_to_upload(row: Any) -> dict[str, Any]:
    row = _mapping(row)
    metadata = _json_load(row["metadata_json"], {})
    return {
        **metadata,
        "filename": row["filename"],
        "user_id": row["user_id"],
        "storage_provider": row.get("storage_provider") or metadata.get("storage_provider") or metadata.get("video_storage_provider") or "",
        "object_key": row.get("object_key") or metadata.get("object_key") or metadata.get("video_object_key") or "",
        "object_url": row.get("object_url") or metadata.get("object_url") or metadata.get("video_object_url") or "",
        "object_error": row.get("object_error") or metadata.get("object_error") or metadata.get("video_object_error") or "",
        "created_at": row["created_at"],
    }


def _upload_object_fields(metadata: dict[str, Any]) -> dict[str, str]:
    return {
        "storage_provider": str(metadata.get("storage_provider") or metadata.get("video_storage_provider") or ""),
        "object_key": str(metadata.get("object_key") or metadata.get("video_object_key") or ""),
        "object_url": str(metadata.get("object_url") or metadata.get("video_object_url") or ""),
        "object_error": str(metadata.get("object_error") or metadata.get("video_object_error") or ""),
    }


def public_task(task: dict[str, Any]) -> dict[str, Any]:
    payload = dict(task)
    payload.pop("payload", None)
    return payload


class TaskStore:
    def __init__(self, path: Path = TASK_STORE_DB_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.engine = create_app_engine(path)
        ensure_schema(self.engine)
        self._migrate_legacy_json()

    def _migrate_legacy_json(self):
        if not LEGACY_TASK_STORE_PATH.exists():
            return
        with self.lock, self.engine.begin() as conn:
            existing = int(conn.execute(select(func.count()).select_from(tasks_table)).scalar_one())
            existing_uploads = int(conn.execute(select(func.count()).select_from(uploads_table)).scalar_one())
            if existing or existing_uploads:
                return
            try:
                data = json.loads(LEGACY_TASK_STORE_PATH.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return
            for task in (data.get("tasks") or {}).values():
                created_at = task.get("created_at") or now_iso()
                conn.execute(
                    tasks_table.insert().values(
                        task_id=task.get("task_id"),
                        user_id=task.get("user_id") or LOCAL_USER_ID,
                        kind=task.get("kind") or "",
                        title=task.get("title") or "",
                        status=task.get("status") or "queued",
                        progress=int(task.get("progress") or 0),
                        message=task.get("message") or "",
                        payload_json=_json_dump(task.get("payload") or {}),
                        result_json=_json_dump(task.get("result")),
                        error=task.get("error"),
                        created_at=created_at,
                        updated_at=task.get("updated_at") or created_at,
                        started_at=task.get("started_at"),
                        finished_at=task.get("finished_at"),
                    )
                )
            for filename, item in (data.get("uploads") or {}).items():
                created_at = item.get("created_at") or now_iso()
                metadata = dict(item)
                metadata.pop("filename", None)
                metadata.pop("user_id", None)
                metadata.pop("created_at", None)
                conn.execute(
                    uploads_table.insert().values(
                        filename=filename,
                        user_id=item.get("user_id") or LOCAL_USER_ID,
                        **_upload_object_fields(metadata),
                        metadata_json=_json_dump(metadata),
                        created_at=created_at,
                    )
                )

    def create_task(
        self,
        task_id: str,
        kind: str,
        title: str,
        payload: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        with self.lock, self.engine.begin() as conn:
            created_at = now_iso()
            task = {
                "task_id": task_id,
                "user_id": user_id or LOCAL_USER_ID,
                "kind": kind,
                "title": title,
                "status": "queued",
                "progress": 0,
                "message": "等待开始",
                "payload": payload or {},
                "result": None,
                "error": None,
                "created_at": created_at,
                "updated_at": created_at,
                "started_at": None,
                "finished_at": None,
            }
            conn.execute(tasks_table.delete().where(tasks_table.c.task_id == task_id))
            conn.execute(
                tasks_table.insert().values(
                    task_id=task["task_id"],
                    user_id=task["user_id"],
                    kind=task["kind"],
                    title=task["title"],
                    status=task["status"],
                    progress=task["progress"],
                    message=task["message"],
                    payload_json=_json_dump(task["payload"]),
                    result_json=_json_dump(task["result"]),
                    error=task["error"],
                    created_at=task["created_at"],
                    updated_at=task["updated_at"],
                    started_at=task["started_at"],
                    finished_at=task["finished_at"],
                )
            )
            self._trim_tasks(conn, task["user_id"])
            return public_task(task)

    def update_task(self, task_id: str, **updates: Any) -> dict[str, Any] | None:
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(select(tasks_table).where(tasks_table.c.task_id == task_id)).first()
            if not row:
                return None
            task = _row_to_task(row)
            task.update(updates)
            task["updated_at"] = now_iso()
            conn.execute(
                tasks_table.update()
                .where(tasks_table.c.task_id == task_id)
                .values(
                    status=task["status"],
                    progress=int(task["progress"] or 0),
                    message=task["message"],
                    payload_json=_json_dump(task.get("payload") or {}),
                    result_json=_json_dump(task.get("result")),
                    error=task.get("error"),
                    updated_at=task["updated_at"],
                    started_at=task.get("started_at"),
                    finished_at=task.get("finished_at"),
                )
            )
            return public_task(task)

    def get_task(self, task_id: str, include_payload: bool = False, user_id: str | None = None) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            query = select(tasks_table).where(tasks_table.c.task_id == task_id)
            if user_id:
                query = query.where(tasks_table.c.user_id == user_id)
            row = conn.execute(query).first()
            if not row:
                return None
            task = _row_to_task(row)
            return task if include_payload else public_task(task)

    def list_tasks(self, limit: int = 30, kind: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        filters = []
        if user_id:
            filters.append(tasks_table.c.user_id == user_id)
        if kind:
            filters.append(tasks_table.c.kind == kind)
        query = select(tasks_table)
        if filters:
            query = query.where(and_(*filters))
        query = query.order_by(tasks_table.c.created_at.desc()).limit(max(1, min(limit, MAX_HISTORY_ITEMS)))
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [public_task(_row_to_task(row)) for row in rows]

    def delete_task(self, task_id: str, user_id: str | None = None) -> bool:
        with self.lock, self.engine.begin() as conn:
            query = tasks_table.delete().where(tasks_table.c.task_id == task_id)
            if user_id:
                query = query.where(tasks_table.c.user_id == user_id)
            result = conn.execute(query)
            return (result.rowcount or 0) > 0

    def record_upload(self, filename: str, metadata: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        with self.lock, self.engine.begin() as conn:
            created_at = metadata.get("created_at") or now_iso()
            item = {
                **metadata,
                "filename": filename,
                "user_id": user_id or LOCAL_USER_ID,
                "created_at": created_at,
            }
            item.update(_upload_object_fields(item))
            metadata_json = dict(item)
            metadata_json.pop("filename", None)
            metadata_json.pop("user_id", None)
            metadata_json.pop("created_at", None)
            metadata_json.pop("storage_provider", None)
            metadata_json.pop("object_key", None)
            metadata_json.pop("object_url", None)
            metadata_json.pop("object_error", None)
            conn.execute(uploads_table.delete().where(uploads_table.c.filename == filename))
            conn.execute(
                uploads_table.insert().values(
                    filename=filename,
                    user_id=item["user_id"],
                    **_upload_object_fields(item),
                    metadata_json=_json_dump(metadata_json),
                    created_at=created_at,
                )
            )
            return item

    def get_upload(self, filename: str, user_id: str | None = None) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            query = select(uploads_table).where(uploads_table.c.filename == filename)
            if user_id:
                query = query.where(uploads_table.c.user_id == user_id)
            row = conn.execute(query).first()
            return _row_to_upload(row) if row else None

    def delete_upload(self, filename: str, user_id: str | None = None) -> bool:
        with self.lock, self.engine.begin() as conn:
            query = uploads_table.delete().where(uploads_table.c.filename == filename)
            if user_id:
                query = query.where(uploads_table.c.user_id == user_id)
            result = conn.execute(query)
            return (result.rowcount or 0) > 0

    def list_uploads(self, limit: int = 80, user_id: str | None = None) -> list[dict[str, Any]]:
        query = select(uploads_table)
        if user_id:
            query = query.where(uploads_table.c.user_id == user_id)
        query = query.order_by(uploads_table.c.created_at.desc()).limit(max(1, min(limit, 200)))
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [_row_to_upload(row) for row in rows]

    def _trim_tasks(self, conn, user_id: str):
        rows = conn.execute(
            select(tasks_table.c.task_id)
            .where(tasks_table.c.user_id == user_id)
            .order_by(tasks_table.c.created_at.desc())
            .offset(MAX_HISTORY_ITEMS)
        ).fetchall()
        if rows:
            task_ids = [row[0] for row in rows]
            conn.execute(tasks_table.delete().where(tasks_table.c.task_id.in_(task_ids)))


task_store = TaskStore()
