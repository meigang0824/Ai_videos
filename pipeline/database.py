from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine
from sqlalchemy.engine import Engine


metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("username", String(255), nullable=False, unique=True, index=True),
    Column("password_hash", Text, nullable=False),
    Column("role", String(32), nullable=False, default="user"),
    Column("status", String(32), nullable=False, default="active"),
    Column("created_at", Integer, nullable=False),
    Column("last_login_at", Integer),
)

tasks_table = Table(
    "tasks",
    metadata,
    Column("task_id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False, default="local", index=True),
    Column("kind", String(64), nullable=False),
    Column("title", String(255), nullable=False),
    Column("status", String(32), nullable=False, index=True),
    Column("progress", Integer, nullable=False),
    Column("message", Text, nullable=False),
    Column("payload_json", Text),
    Column("result_json", Text),
    Column("error", Text),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("started_at", String(64)),
    Column("finished_at", String(64)),
)

uploads_table = Table(
    "uploads",
    metadata,
    Column("filename", String(255), primary_key=True),
    Column("user_id", String(64), nullable=False, default="local", index=True),
    Column("metadata_json", Text),
    Column("created_at", String(64), nullable=False),
)

voices_table = Table(
    "voices",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("user_id", String(64), nullable=False, default="local", index=True),
    Column("name", String(255), nullable=False),
    Column("kind", String(32), nullable=False, default="local"),
    Column("ref_wav", Text, nullable=False),
    Column("ref_text", Text),
    Column("size_bytes", Integer, nullable=False, default=0),
    Column("storage_provider", String(64)),
    Column("object_key", Text),
    Column("object_url", Text),
    Column("object_error", Text),
    Column("meta_object_key", Text),
    Column("meta_object_url", Text),
    Column("meta_object_error", Text),
    Column("created_at", String(64), nullable=False),
)


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def database_url(sqlite_path: Path) -> str:
    return os.getenv("DATABASE_URL", "").strip() or _sqlite_url(sqlite_path)


def create_app_engine(sqlite_path: Path) -> Engine:
    url = database_url(sqlite_path)
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite:"):
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def ensure_schema(engine: Engine):
    metadata.create_all(engine)
