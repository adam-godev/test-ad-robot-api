from typing import Annotated

from fastapi import APIRouter, Header, Query

from app.api.dependencies import DbSession, KeitaroDep, SettingsDep
from app.schemas import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignListResponse,
    CampaignStatsResponse,
    HealthResponse,
    OfferAttachRequest,
    OfferSearchResponse,
    OffersUpdateResponse,
    BulkActionResponse,
    StreamOfferMutationRequest,
    SyncResponse,
)
from app.services.campaigns import CampaignService


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/offers/search", response_model=OfferSearchResponse)
def search_offers(
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    return {"items": CampaignService(db, keitaro, settings).search_offers(q, limit)}


@router.post("/campaigns", response_model=CampaignDetailResponse, status_code=201)
def create_campaign(
    request: CampaignCreateRequest,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CampaignDetailResponse:
    return CampaignService(db, keitaro, settings).create_campaign(request, idempotency_key)


@router.post("/campaigns/fetch-from-kt", response_model=SyncResponse)
def fetch_from_keitaro(db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).sync_from_keitaro()


@router.post("/campaigns/push-to-kt", response_model=BulkActionResponse)
def push_campaign_pending(db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).push_campaign_pending()


@router.post("/campaigns/cancel-pending", response_model=BulkActionResponse)
def cancel_campaign_pending(db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).cancel_campaign_pending()


@router.get("/campaigns", response_model=CampaignListResponse)
def list_campaigns(
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    items, total = CampaignService(db, keitaro, settings).list_campaigns(limit, offset)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailResponse)
def get_campaign(
    campaign_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
    refresh: bool = False,
) -> CampaignDetailResponse:
    return CampaignService(db, keitaro, settings).get_campaign(campaign_id, refresh=refresh)


@router.post("/campaigns/{campaign_id}/stage-delete", response_model=CampaignDetailResponse)
def stage_delete_campaign(
    campaign_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> CampaignDetailResponse:
    return CampaignService(db, keitaro, settings).stage_delete_campaign(campaign_id)


@router.post("/campaigns/{campaign_id}/restore", response_model=CampaignDetailResponse)
def restore_campaign(campaign_id: int, db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> CampaignDetailResponse:
    return CampaignService(db, keitaro, settings).restore_campaign(campaign_id)


@router.get("/campaigns/{campaign_id}/keitaro-streams", response_model=CampaignDetailResponse)
def get_keitaro_streams(
    campaign_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> CampaignDetailResponse:
    return CampaignService(db, keitaro, settings).get_keitaro_streams(campaign_id)


@router.post("/campaigns/{campaign_id}/offers", response_model=OffersUpdateResponse)
def add_offer(
    campaign_id: int,
    request: OfferAttachRequest,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).add_offer(campaign_id, request.offer_id)


@router.post(
    "/campaigns/{campaign_id}/streams/{flow_id}/offers",
    response_model=OffersUpdateResponse,
)
def stage_add_stream_offer(
    campaign_id: int,
    flow_id: int,
    request: StreamOfferMutationRequest,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).stage_add_stream_offer(
        campaign_id,
        flow_id,
        request.offer_id,
        request.name,
    )


@router.post(
    "/campaigns/{campaign_id}/streams/{flow_id}/offers/{offer_id}/stage-remove",
    response_model=OffersUpdateResponse,
)
def stage_remove_stream_offer(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).stage_remove_stream_offer(campaign_id, flow_id, offer_id)


@router.post(
    "/campaigns/{campaign_id}/streams/{flow_id}/offers/{offer_id}/restore",
    response_model=OffersUpdateResponse,
)
def restore_stream_offer(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).restore_stream_offer(campaign_id, flow_id, offer_id)


@router.post(
    "/campaigns/{campaign_id}/streams/{flow_id}/offers/{offer_id}/toggle-pin",
    response_model=OffersUpdateResponse,
)
def toggle_stream_offer_pin(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).toggle_stream_offer_pin(campaign_id, flow_id, offer_id)


@router.post("/campaigns/{campaign_id}/streams/push-to-kt", response_model=BulkActionResponse)
def push_stream_changes(campaign_id: int, db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).push_stream_changes(campaign_id)


@router.post("/campaigns/{campaign_id}/streams/cancel-pending", response_model=BulkActionResponse)
def cancel_stream_changes(campaign_id: int, db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).cancel_stream_changes(campaign_id)


@router.post("/campaigns/{campaign_id}/streams/{flow_id}/push-to-kt", response_model=BulkActionResponse)
def push_one_stream_changes(
    campaign_id: int,
    flow_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).push_stream_changes(campaign_id, flow_id=flow_id)


@router.post("/campaigns/{campaign_id}/streams/{flow_id}/cancel-pending", response_model=BulkActionResponse)
def cancel_one_stream_changes(
    campaign_id: int,
    flow_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
) -> dict:
    return CampaignService(db, keitaro, settings).cancel_stream_changes(campaign_id, flow_id=flow_id)


@router.delete("/campaigns/{campaign_id}/offers/{offer_id}", response_model=OffersUpdateResponse)
def delete_offer(campaign_id: int, offer_id: int, db: DbSession, keitaro: KeitaroDep, settings: SettingsDep) -> dict:
    return CampaignService(db, keitaro, settings).delete_offer(campaign_id, offer_id)


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStatsResponse)
def get_stats(
    campaign_id: int,
    db: DbSession,
    keitaro: KeitaroDep,
    settings: SettingsDep,
    period: str = "today",
) -> dict:
    return CampaignService(db, keitaro, settings).get_stats(campaign_id, period)
