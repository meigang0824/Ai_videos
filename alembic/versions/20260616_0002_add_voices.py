"""add voices table

Revision ID: 20260616_0002
Revises: 20260615_0001
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_0002"
down_revision = "20260615_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ref_wav", sa.Text(), nullable=False),
        sa.Column("ref_text", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_provider", sa.String(length=64), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("object_url", sa.Text(), nullable=True),
        sa.Column("object_error", sa.Text(), nullable=True),
        sa.Column("meta_object_key", sa.Text(), nullable=True),
        sa.Column("meta_object_url", sa.Text(), nullable=True),
        sa.Column("meta_object_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_voices_user_id", "voices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_voices_user_id", table_name="voices")
    op.drop_table("voices")
