"""Add Keitaro sync and pending action fields.

Revision ID: 20260704_0002
Revises: 20260704_0001
Create Date: 2026-07-04 00:10:00
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0002"
down_revision: str | None = "20260704_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("pending_action", sa.String(length=32), nullable=True))
    op.add_column("campaigns", sa.Column("metrics", sa.JSON(), nullable=True))
    op.add_column("campaigns", sa.Column("kt_payload", sa.JSON(), nullable=True))
    op.add_column("flows", sa.Column("pending_action", sa.String(length=32), nullable=True))
    op.add_column("flows", sa.Column("metrics", sa.JSON(), nullable=True))
    op.add_column("flows", sa.Column("kt_payload", sa.JSON(), nullable=True))
    op.add_column("campaign_offers", sa.Column("pending_action", sa.String(length=32), nullable=True))
    op.add_column("campaign_offers", sa.Column("stats", sa.JSON(), nullable=True))
    op.add_column("campaign_offers", sa.Column("trends", sa.JSON(), nullable=True))
    op.add_column("campaign_offers", sa.Column("kt_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("campaign_offers", "kt_payload")
    op.drop_column("campaign_offers", "trends")
    op.drop_column("campaign_offers", "stats")
    op.drop_column("campaign_offers", "pending_action")
    op.drop_column("flows", "kt_payload")
    op.drop_column("flows", "metrics")
    op.drop_column("flows", "pending_action")
    op.drop_column("campaigns", "kt_payload")
    op.drop_column("campaigns", "metrics")
    op.drop_column("campaigns", "pending_action")
