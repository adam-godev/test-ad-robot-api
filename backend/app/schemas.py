from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str


class OfferSearchItem(BaseModel):
    id: int
    name: str
    country: str | None = None
    state: str | None = None
    affiliate_network: str | None = None
    url: str | None = None


class OfferSearchResponse(BaseModel):
    items: list[OfferSearchItem]


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo_codes: list[str] = Field(min_length=1)
    offer_id: int = Field(gt=0)
    alias: str | None = None


class OfferAttachRequest(BaseModel):
    offer_id: int = Field(gt=0)


class CampaignOfferResponse(BaseModel):
    offer_id: int
    name: str
    weight: int
    position: int | None = None
    is_pinned: bool = False
    pending_action: str | None = None
    stats: dict | None = None
    trends: dict | None = None


class FlowResponse(BaseModel):
    id: int
    keitaro_flow_id: int | None
    name: str
    position: int
    type: str
    redirect_url: str | None
    geo_codes: list[str]
    offers: list[CampaignOfferResponse]
    status: str | None = None
    pending_action: str | None = None
    metrics: dict | None = None
    has_pending_changes: bool = False


class StatsResponse(BaseModel):
    clicks: int = 0
    unique_clicks: int = 0
    bots: int = 0
    conversions: int = 0
    revenue: float = 0
    cost: float = 0
    profit: float = 0
    cr: float = 0


class CampaignDetailResponse(BaseModel):
    id: int
    keitaro_campaign_id: int | None
    name: str
    alias: str
    campaign_url: str
    keitaro_admin_url: str | None = None
    geo_codes: list[str]
    status: str
    pending_action: str | None = None
    metrics: dict | None = None
    flows: list[FlowResponse]
    stats: StatsResponse


class CampaignListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keitaro_campaign_id: int | None
    name: str
    alias: str
    campaign_url: str
    keitaro_admin_url: str | None = None
    geo_codes: list[str]
    status: str
    pending_action: str | None = None
    metrics: dict | None = None
    stream_count: int | None = None
    has_pending_changes: bool = False
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignListItem]
    limit: int
    offset: int
    total: int


class OffersUpdateResponse(BaseModel):
    campaign_id: int
    flow_id: int
    offers: list[CampaignOfferResponse]


class SyncResponse(BaseModel):
    campaigns_imported: int
    flows_imported: int
    offers_imported: int


class BulkActionResponse(BaseModel):
    campaigns_updated: int = 0
    streams_updated: int = 0
    offers_updated: int = 0


class StreamOfferMutationRequest(BaseModel):
    offer_id: int = Field(gt=0)
    name: str | None = None


class FlowStatsResponse(BaseModel):
    flow_id: int
    name: str
    clicks: int = 0
    unique_clicks: int = 0
    bots: int = 0


class CampaignStatsResponse(BaseModel):
    period: str
    campaign_id: int
    flows: list[FlowStatsResponse]
