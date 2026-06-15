"""initial schema

Revision ID: 20260615_0001
Revises:
Create Date: 2026-06-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260615_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.Integer(), nullable=True),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "uploads",
        sa.Column("filename", sa.String(length=255), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_uploads_user_id", "uploads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_uploads_user_id", table_name="uploads")
    op.drop_table("uploads")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
