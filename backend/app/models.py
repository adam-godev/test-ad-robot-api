from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


BigInt = BigInteger().with_variant(Integer, "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    keitaro_campaign_id: Mapped[int | None] = mapped_column(BigInt, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    campaign_url: Mapped[str] = mapped_column(Text, nullable=False)
    geo_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    domain_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    domain_url: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    traffic_source_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="creating")
    pending_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kt_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    flows: Mapped[list["Flow"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="Flow.position",
    )
    offers: Mapped[list["CampaignOffer"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignOffer.position",
    )


class Flow(TimestampMixin, Base):
    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    keitaro_flow_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    geo_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    pending_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kt_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    campaign: Mapped[Campaign] = relationship(back_populates="flows")
    offers: Mapped[list["CampaignOffer"]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        order_by="CampaignOffer.position",
    )


class CampaignOffer(TimestampMixin, Base):
    __tablename__ = "campaign_offers"
    __table_args__ = (UniqueConstraint("campaign_id", "flow_id", "keitaro_offer_id", name="uq_campaign_flow_offer"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    keitaro_offer_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trends: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kt_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    campaign: Mapped[Campaign] = relationship(back_populates="offers")
    flow: Mapped[Flow] = relationship(back_populates="offers")


class OperationLog(TimestampMixin, Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
