"""add service configs table

Revision ID: 20260616_0003
Revises: 20260616_0002
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_0003"
down_revision = "20260616_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_configs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("service_configs")
