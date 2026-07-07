"""Add offer pin state.

Revision ID: 20260706_0003
Revises: 20260704_0002
Create Date: 2026-07-06 00:00:00
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260706_0003"
down_revision: str | None = "20260704_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_offers",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("campaign_offers", "is_pinned")
