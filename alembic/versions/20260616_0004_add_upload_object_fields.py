"""add upload object storage fields

Revision ID: 20260616_0004
Revises: 20260616_0003
Create Date: 2026-06-16
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260616_0004"
down_revision = "20260616_0003"
branch_labels = None
depends_on = None


uploads = sa.table(
    "uploads",
    sa.column("filename", sa.String),
    sa.column("storage_provider", sa.String),
    sa.column("object_key", sa.Text),
    sa.column("object_url", sa.Text),
    sa.column("object_error", sa.Text),
    sa.column("metadata_json", sa.Text),
)


def _metadata(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def upgrade() -> None:
    op.add_column("uploads", sa.Column("storage_provider", sa.String(length=64), nullable=True))
    op.add_column("uploads", sa.Column("object_key", sa.Text(), nullable=True))
    op.add_column("uploads", sa.Column("object_url", sa.Text(), nullable=True))
    op.add_column("uploads", sa.Column("object_error", sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.select(uploads.c.filename, uploads.c.metadata_json)).fetchall()
    for row in rows:
        metadata = _metadata(row.metadata_json)
        values = {
            "storage_provider": metadata.get("storage_provider") or metadata.get("video_storage_provider") or "",
            "object_key": metadata.get("object_key") or metadata.get("video_object_key") or "",
            "object_url": metadata.get("object_url") or metadata.get("video_object_url") or "",
            "object_error": metadata.get("object_error") or metadata.get("video_object_error") or "",
        }
        if any(values.values()):
            bind.execute(uploads.update().where(uploads.c.filename == row.filename).values(**values))


def downgrade() -> None:
    op.drop_column("uploads", "object_error")
    op.drop_column("uploads", "object_url")
    op.drop_column("uploads", "object_key")
    op.drop_column("uploads", "storage_provider")
