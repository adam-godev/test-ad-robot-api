"""Initial schema.

Revision ID: 20260704_0001
Revises:
Create Date: 2026-07-04 00:00:00
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("keitaro_campaign_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False, unique=True),
        sa.Column("campaign_url", sa.Text(), nullable=False),
        sa.Column("geo_codes", sa.JSON(), nullable=False),
        sa.Column("domain_id", sa.BigInteger(), nullable=True),
        sa.Column("domain_url", sa.Text(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("traffic_source_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "flows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.BigInteger(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keitaro_flow_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=True),
        sa.Column("geo_codes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "campaign_offers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.BigInteger(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_id", sa.BigInteger(), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keitaro_offer_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("campaign_id", "flow_id", "keitaro_offer_id", name="uq_campaign_flow_offer"),
    )
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_operation_logs_idempotency_key", "operation_logs", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_operation_logs_idempotency_key", table_name="operation_logs")
    op.drop_table("operation_logs")
    op.drop_table("campaign_offers")
    op.drop_table("flows")
    op.drop_table("campaigns")

