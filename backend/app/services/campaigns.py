import time
from typing import Any

from sqlalchemy import Select, case, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.keitaro.client import (
    KeitaroCampaign,
    KeitaroClient,
    KeitaroError,
    KeitaroOffer,
    KeitaroStream,
)
from app.integrations.keitaro.payloads import (
    campaign_payload,
    flow_1_payload,
    flow_2_payload,
    offers_stream_update_payload,
)
from app.models import Campaign, CampaignOffer, Flow, OperationLog
from app.schemas import CampaignCreateRequest, CampaignDetailResponse, CampaignListItem
from app.services.aliases import clean_alias, generate_alias
from app.services.geo import normalize_geo_codes
from app.services.weights import (
    OfferWeightInput,
    distribute_weights,
    with_distributed_weights,
)


class CampaignService:
    DEFAULT_REDIRECT_URL = "https://google.com"
    REPORT_TIMEZONE = "Europe/Berlin"
    PENDING_OFFER_ACTIONS = {"add", "remove", "restore"}
    INACTIVE_OFFER_ACTIONS = {"remove", "removed"}

    def __init__(self, db: Session, keitaro: KeitaroClient, settings: Settings) -> None:
        self.db = db
        self.keitaro = keitaro
        self.settings = settings

    def search_offers(self, query: str, limit: int) -> list[dict[str, Any]]:
        query = query.strip()
        if len(query) < 1:
            raise AppError(422, "VALIDATION_ERROR", "Search query must not be empty")
        limit = max(1, min(limit, 50))
        try:
            offers = self.keitaro.search_offers(query, limit)
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc
        return [self._offer_to_dict(offer) for offer in offers]

    def create_campaign(
        self, request: CampaignCreateRequest, idempotency_key: str | None
    ) -> CampaignDetailResponse:
        request_payload = request.model_dump()
        if idempotency_key:
            previous = self._get_previous_idempotent_operation(idempotency_key)
            if previous is not None:
                if previous.request_payload != request_payload:
                    raise AppError(
                        409,
                        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_BODY",
                        "Idempotency-Key was reused with a different request body",
                    )
                if previous.status == "success" and previous.response_payload:
                    return CampaignDetailResponse.model_validate(
                        previous.response_payload
                    )
                raise AppError(
                    409,
                    "IDEMPOTENCY_OPERATION_NOT_REPLAYABLE",
                    "Previous operation is not replayable",
                )

        started_at = time.monotonic()
        operation = OperationLog(
            operation_type="create_campaign",
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            status="started",
        )
        self.db.add(operation)
        self.db.commit()
        self.db.refresh(operation)

        campaign: Campaign | None = None
        keitaro_campaign_id: int | None = None

        try:
            name = request.name.strip()
            if not name:
                raise AppError(
                    422, "VALIDATION_ERROR", "Campaign name must not be empty"
                )
            geo_codes = normalize_geo_codes(request.geo_codes)
            alias = clean_alias(request.alias) or self._generate_unique_alias()

            if self._alias_exists(alias):
                raise AppError(
                    409,
                    "CAMPAIGN_ALIAS_ALREADY_EXISTS",
                    "Campaign alias already exists",
                )

            offer = self.keitaro.get_offer(request.offer_id)

            campaign = Campaign(
                name=name,
                alias=alias,
                campaign_url=self._build_campaign_url(
                    self._campaign_domain_url(), alias
                ),
                geo_codes=geo_codes,
                domain_id=self.settings.keitaro_domain_id,
                domain_url=self._campaign_domain_url(),
                group_id=self.settings.keitaro_group_id,
                traffic_source_id=self.settings.keitaro_traffic_source_id,
                status="creating",
            )
            self.db.add(campaign)
            self.db.commit()
            self.db.refresh(campaign)

            kt_campaign = self.keitaro.create_campaign(
                campaign_payload(
                    name=name,
                    alias=alias,
                    domain_id=self.settings.keitaro_domain_id,
                    group_id=self.settings.keitaro_group_id,
                    traffic_source_id=self.settings.keitaro_traffic_source_id,
                )
            )
            keitaro_campaign_id = kt_campaign.id
            campaign.keitaro_campaign_id = keitaro_campaign_id
            campaign.domain_id = (
                kt_campaign.domain_id or self.settings.keitaro_domain_id
            )
            campaign.group_id = kt_campaign.group_id or self.settings.keitaro_group_id
            campaign.traffic_source_id = (
                kt_campaign.traffic_source_id or self.settings.keitaro_traffic_source_id
            )
            campaign.kt_payload = kt_campaign.payload or {}
            self.db.commit()

            flow1_stream = self.keitaro.create_stream(
                flow_1_payload(
                    campaign_id=keitaro_campaign_id,
                    geo_codes=geo_codes,
                    redirect_url=self.DEFAULT_REDIRECT_URL,
                )
            )
            offers = with_distributed_weights(
                [OfferWeightInput(offer_id=offer.id, name=offer.name)]
            )
            flow2_stream = self.keitaro.create_stream(
                flow_2_payload(campaign_id=keitaro_campaign_id, offers=offers)
            )

            flow1 = Flow(
                campaign_id=campaign.id,
                keitaro_flow_id=flow1_stream.id,
                name="Flow 1",
                position=1,
                kind="geo_redirect",
                redirect_url=self.DEFAULT_REDIRECT_URL,
                geo_codes=geo_codes,
                status="active",
            )
            flow2 = Flow(
                campaign_id=campaign.id,
                keitaro_flow_id=flow2_stream.id,
                name="Flow 2",
                position=2,
                kind="offers_fallback",
                redirect_url=None,
                geo_codes=[],
                status="active",
            )
            self.db.add_all([flow1, flow2])
            self.db.flush()
            self.db.add(
                CampaignOffer(
                    campaign_id=campaign.id,
                    flow_id=flow2.id,
                    keitaro_offer_id=offer.id,
                    name=offer.name,
                    weight=100,
                    position=1,
                )
            )
            campaign.status = "active"
            operation.campaign_id = campaign.id
            self.db.commit()
            self.db.refresh(campaign)

            response = self.serialize_campaign(campaign)
            operation.status = "success"
            operation.response_payload = response.model_dump(mode="json")
            operation.duration_seconds = time.monotonic() - started_at
            self.db.commit()
            return response
        except ValueError as exc:
            app_error = AppError(422, "VALIDATION_ERROR", str(exc))
            self._mark_operation_failed(operation, app_error, started_at, campaign)
            raise app_error from exc
        except AppError as exc:
            self._mark_operation_failed(operation, exc, started_at, campaign)
            raise
        except KeitaroError as exc:
            app_error = self._keitaro_to_app_error(exc)
            self._try_archive_partial_campaign(keitaro_campaign_id, app_error)
            self._mark_operation_failed(operation, app_error, started_at, campaign)
            raise app_error from exc

    def sync_from_keitaro(self) -> dict[str, int]:
        try:
            kt_campaigns = self.keitaro.list_campaigns()
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc

        counts = {"campaigns_imported": 0, "flows_imported": 0, "offers_imported": 0}
        synced_campaign_ids: set[int] = set()
        for kt_campaign in kt_campaigns:
            synced_campaign_ids.add(kt_campaign.id)
            campaign, campaign_counts = self._sync_keitaro_campaign(kt_campaign)
            for key, value in campaign_counts.items():
                counts[key] += value

        stale_statement = select(Campaign).where(
            Campaign.keitaro_campaign_id.is_not(None),
            Campaign.pending_action.is_(None),
            Campaign.status != "archived",
        )
        if synced_campaign_ids:
            stale_statement = stale_statement.where(
                Campaign.keitaro_campaign_id.not_in(synced_campaign_ids)
            )
        stale_campaigns = self.db.scalars(stale_statement).all()
        for campaign in stale_campaigns:
            campaign.status = "archived"

        self.db.commit()
        return counts

    def list_campaigns(
        self, limit: int, offset: int
    ) -> tuple[list[CampaignListItem], int]:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        visible_campaigns = Campaign.status != "archived"
        total = (
            self.db.scalar(
                select(func.count()).select_from(Campaign).where(visible_campaigns)
            )
            or 0
        )
        campaigns = self.db.scalars(
            select(Campaign)
            .where(visible_campaigns)
            .order_by(
                case((Campaign.pending_action == "delete", 1), else_=0),
                desc(Campaign.created_at),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [self._campaign_list_item(campaign) for campaign in campaigns], int(
            total
        )

    def get_campaign(
        self, campaign_id: int, refresh: bool = False
    ) -> CampaignDetailResponse:
        campaign = self._get_campaign_or_404(campaign_id)
        if refresh and campaign.pending_action != "delete":
            campaign = self.refresh_campaign_from_keitaro(campaign)
        return self.serialize_campaign(campaign)

    def refresh_campaign_from_keitaro(self, campaign: Campaign) -> Campaign:
        if campaign.keitaro_campaign_id is None:
            return campaign
        try:
            kt_campaign = self.keitaro.get_campaign(campaign.keitaro_campaign_id)
        except KeitaroError as exc:
            if exc.http_status == 404:
                campaign.pending_action = None
                campaign.status = "archived"
                self.db.commit()
                self.db.refresh(campaign)
                return campaign
            raise self._keitaro_to_app_error(exc) from exc

        synced_campaign, _ = self._sync_keitaro_campaign(kt_campaign, campaign)
        self._refresh_campaign_report_metrics(synced_campaign)
        self.db.commit()
        self.db.refresh(synced_campaign)
        return synced_campaign

    def stage_delete_campaign(self, campaign_id: int) -> CampaignDetailResponse:
        campaign = self._get_campaign_or_404(campaign_id)
        campaign.pending_action = "delete"
        campaign.status = "pending_delete"
        self.db.commit()
        self.db.refresh(campaign)
        return self.serialize_campaign(campaign)

    def restore_campaign(self, campaign_id: int) -> CampaignDetailResponse:
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign.pending_action == "delete":
            campaign.pending_action = None
            campaign.status = "active"
        self.db.commit()
        self.db.refresh(campaign)
        return self.serialize_campaign(campaign)

    def cancel_campaign_pending(self) -> dict[str, int]:
        campaigns = self.db.scalars(
            select(Campaign).where(Campaign.pending_action == "delete")
        ).all()
        for campaign in campaigns:
            campaign.pending_action = None
            campaign.status = "active"
        self.db.commit()
        return {"campaigns_updated": len(campaigns)}

    def push_campaign_pending(self) -> dict[str, int]:
        campaigns = self.db.scalars(
            select(Campaign).where(Campaign.pending_action == "delete")
        ).all()
        updated = 0
        for campaign in campaigns:
            if campaign.keitaro_campaign_id is not None:
                try:
                    self.keitaro.archive_campaign(campaign.keitaro_campaign_id)
                except KeitaroError as exc:
                    raise self._keitaro_to_app_error(exc) from exc
            campaign.pending_action = None
            campaign.status = "archived"
            updated += 1
        self.db.commit()
        return {"campaigns_updated": updated}

    def add_offer(self, campaign_id: int, offer_id: int) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow2 = self._get_flow2_or_404(campaign)
        existing = self._flow2_offers(flow2)
        if any(offer.keitaro_offer_id == offer_id for offer in existing):
            raise AppError(
                409, "OFFER_ALREADY_ATTACHED", "Offer is already attached to Flow 2"
            )

        try:
            self._assert_keitaro_flow_exists(campaign, flow2)
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc

        try:
            offer = self.keitaro.get_offer(offer_id)
        except KeitaroError as exc:
            if exc.http_status == 404:
                raise AppError(
                    404, "OFFER_NOT_FOUND_IN_KEITARO", "Offer was not found in Keitaro"
                ) from exc
            raise self._keitaro_to_app_error(exc) from exc

        weighted = self._weighted_offer_payload(
            [OfferWeightInput(offer.keitaro_offer_id, offer.name) for offer in existing]
            + [OfferWeightInput(offer.id, offer.name)]
        )
        try:
            self.keitaro.update_stream(
                flow2.keitaro_flow_id,
                flow_2_payload(
                    campaign_id=campaign.keitaro_campaign_id, offers=weighted
                ),
            )
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc

        for index, local_offer in enumerate(existing):
            local_offer.weight = int(weighted[index]["weight"])
            local_offer.position = index + 1
        self.db.add(
            CampaignOffer(
                campaign_id=campaign.id,
                flow_id=flow2.id,
                keitaro_offer_id=offer.id,
                name=offer.name,
                weight=int(weighted[-1]["weight"]),
                position=len(weighted),
            )
        )
        self.db.commit()
        self.db.refresh(flow2)
        return self._offers_update_response(campaign, flow2)

    def delete_offer(self, campaign_id: int, offer_id: int) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow2 = self._get_flow2_or_404(campaign)
        existing = self._flow2_offers(flow2)
        offer_to_delete = next(
            (offer for offer in existing if offer.keitaro_offer_id == offer_id), None
        )
        if offer_to_delete is None:
            raise AppError(404, "OFFER_NOT_ATTACHED", "Offer is not attached to Flow 2")

        remaining = [offer for offer in existing if offer.keitaro_offer_id != offer_id]
        weighted = (
            self._weighted_offer_payload(
                [
                    OfferWeightInput(offer.keitaro_offer_id, offer.name)
                    for offer in remaining
                ]
            )
            if remaining
            else []
        )

        try:
            self._assert_keitaro_flow_exists(campaign, flow2)
            self.keitaro.update_stream(
                flow2.keitaro_flow_id,
                flow_2_payload(
                    campaign_id=campaign.keitaro_campaign_id, offers=weighted
                ),
            )
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc

        self.db.delete(offer_to_delete)
        for index, local_offer in enumerate(remaining):
            local_offer.weight = int(weighted[index]["weight"])
            local_offer.position = index + 1
        self.db.commit()
        self.db.refresh(flow2)
        return self._offers_update_response(campaign, flow2)

    def get_stats(self, campaign_id: int, period: str) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        return {
            "period": period,
            "campaign_id": campaign.id,
            "flows": [
                {
                    "flow_id": flow.id,
                    "name": flow.name,
                    "clicks": int((flow.metrics or {}).get("clicks") or 0),
                    "unique_clicks": int(
                        (flow.metrics or {}).get("unique_clicks")
                        or (flow.metrics or {}).get("uniques")
                        or 0
                    ),
                    "bots": int((flow.metrics or {}).get("bots") or 0),
                }
                for flow in sorted(campaign.flows, key=lambda item: item.position)
            ],
        }

    def get_keitaro_streams(self, campaign_id: int) -> CampaignDetailResponse:
        return self.get_campaign(campaign_id)

    def stage_add_stream_offer(
        self,
        campaign_id: int,
        flow_id: int,
        offer_id: int,
        offer_name: str | None = None,
    ) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow = self._get_flow_or_404(campaign, flow_id)
        if flow.kind != "offers_fallback" and flow.offers:
            raise AppError(
                409,
                "STREAM_DOES_NOT_ACCEPT_OFFERS",
                "Offers can be edited only in offer streams",
            )
        if flow.kind != "offers_fallback":
            flow.kind = "offers_fallback"
            flow.redirect_url = None
        existing = self._flow2_offers(flow)
        attached = next(
            (offer for offer in existing if offer.keitaro_offer_id == offer_id), None
        )
        if attached and attached.pending_action not in self.INACTIVE_OFFER_ACTIONS:
            raise AppError(
                409,
                "OFFER_ALREADY_ATTACHED",
                "Offer is already attached to this stream",
            )
        if attached and attached.pending_action in self.INACTIVE_OFFER_ACTIONS:
            attached.pending_action = (
                None if attached.pending_action == "remove" else "restore"
            )
            self._recompute_flow_weights(flow)
            self.db.commit()
            return self._offers_update_response(campaign, flow)

        if offer_name:
            resolved_offer_id = offer_id
            resolved_offer_name = offer_name.strip() or f"Offer {offer_id}"
        else:
            try:
                offer = self.keitaro.get_offer(offer_id)
            except KeitaroError as exc:
                if exc.http_status == 404:
                    raise AppError(
                        404,
                        "OFFER_NOT_FOUND_IN_KEITARO",
                        "Offer was not found in Keitaro",
                    ) from exc
                raise self._keitaro_to_app_error(exc) from exc
            resolved_offer_id = offer.id
            resolved_offer_name = offer.name

        new_offer = CampaignOffer(
            campaign_id=campaign.id,
            flow_id=flow.id,
            keitaro_offer_id=resolved_offer_id,
            name=resolved_offer_name,
            weight=0,
            position=len(existing) + 1,
            is_pinned=False,
            pending_action="add",
            stats={},
            trends={},
            kt_payload={"id": resolved_offer_id, "name": resolved_offer_name},
        )
        flow.offers.append(new_offer)
        self.db.add(new_offer)
        self._recompute_flow_weights(flow)
        self.db.commit()
        self.db.refresh(flow)
        return self._offers_update_response(campaign, flow)

    def stage_remove_stream_offer(
        self, campaign_id: int, flow_id: int, offer_id: int
    ) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow = self._get_flow_or_404(campaign, flow_id)
        offer = next(
            (item for item in flow.offers if item.keitaro_offer_id == offer_id), None
        )
        if offer is None:
            raise AppError(
                404, "OFFER_NOT_ATTACHED", "Offer is not attached to this stream"
            )
        if offer.pending_action == "add":
            self.db.delete(offer)
            self.db.flush()
            self.db.expire(flow, ["offers"])
        elif offer.pending_action == "restore":
            offer.pending_action = "removed"
            offer.weight = 0
            offer.is_pinned = False
        else:
            offer.pending_action = "remove"
            offer.is_pinned = False
        self._recompute_flow_weights(flow)
        self.db.commit()
        self.db.refresh(flow)
        return self._offers_update_response(campaign, flow)

    def restore_stream_offer(
        self, campaign_id: int, flow_id: int, offer_id: int
    ) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow = self._get_flow_or_404(campaign, flow_id)
        offer = next(
            (item for item in flow.offers if item.keitaro_offer_id == offer_id), None
        )
        if offer is None:
            raise AppError(
                404, "OFFER_NOT_ATTACHED", "Offer is not attached to this stream"
            )
        if offer.pending_action == "remove":
            offer.pending_action = None
        elif offer.pending_action == "removed":
            offer.pending_action = "restore"
        self._recompute_flow_weights(flow)
        self.db.commit()
        return self._offers_update_response(campaign, flow)

    def toggle_stream_offer_pin(
        self, campaign_id: int, flow_id: int, offer_id: int
    ) -> dict[str, Any]:
        campaign = self._get_campaign_or_404(campaign_id)
        flow = self._get_flow_or_404(campaign, flow_id)
        offer = next(
            (item for item in flow.offers if item.keitaro_offer_id == offer_id), None
        )
        if offer is None:
            raise AppError(
                404, "OFFER_NOT_ATTACHED", "Offer is not attached to this stream"
            )
        if self._offer_is_inactive(offer):
            raise AppError(
                409, "CANNOT_PIN_INACTIVE_OFFER", "Inactive offers cannot be pinned"
            )
        offer.is_pinned = not offer.is_pinned
        self._recompute_flow_weights(flow)
        self.db.commit()
        return self._offers_update_response(campaign, flow)

    def cancel_stream_changes(
        self, campaign_id: int, flow_id: int | None = None
    ) -> dict[str, int]:
        campaign = self._get_campaign_or_404(campaign_id)
        flows = (
            [self._get_flow_or_404(campaign, flow_id)]
            if flow_id is not None
            else list(campaign.flows)
        )
        updated = 0
        for flow in flows:
            changed_flow = False
            for offer in list(flow.offers):
                if offer.pending_action == "add":
                    self.db.delete(offer)
                    updated += 1
                    changed_flow = True
                elif offer.pending_action == "remove":
                    offer.pending_action = None
                    updated += 1
                    changed_flow = True
                elif offer.pending_action == "restore":
                    offer.pending_action = "removed"
                    offer.weight = 0
                    offer.is_pinned = False
                    updated += 1
                    changed_flow = True
            if changed_flow:
                self.db.flush()
                self.db.expire(flow, ["offers"])
            self._recompute_flow_weights(flow)
        self.db.commit()
        return {"offers_updated": updated}

    def push_stream_changes(
        self, campaign_id: int, flow_id: int | None = None
    ) -> dict[str, int]:
        campaign = self._get_campaign_or_404(campaign_id)
        flows = (
            [self._get_flow_or_404(campaign, flow_id)]
            if flow_id is not None
            else list(campaign.flows)
        )
        updated_streams = 0
        for flow in flows:
            pending = [
                offer for offer in flow.offers if self._offer_has_pending_change(offer)
            ]
            if not pending:
                continue
            if campaign.keitaro_campaign_id is None or flow.keitaro_flow_id is None:
                raise AppError(
                    424, "KEITARO_FLOW_NOT_FOUND", "Stream is not linked to Keitaro"
                )
            self._recompute_flow_weights(flow)
            active_offers = [
                offer
                for offer in self._flow2_offers(flow)
                if not self._offer_is_inactive(offer)
            ]
            weighted = self._weighted_offer_payload_from_rows(active_offers)
            try:
                self.keitaro.update_stream(
                    flow.keitaro_flow_id,
                    self._stream_offers_update_payload(campaign, flow, weighted),
                )
            except KeitaroError as exc:
                raise self._keitaro_to_app_error(exc) from exc
            for index, offer in enumerate(active_offers, start=1):
                offer.position = index
                if offer.pending_action in ("add", "restore"):
                    offer.pending_action = None
            for offer in [
                offer for offer in flow.offers if offer.pending_action == "remove"
            ]:
                offer.pending_action = "removed"
                offer.weight = 0
                offer.is_pinned = False
            updated_streams += 1
            self._recompute_flow_weights(flow)
        self.db.commit()
        return {"streams_updated": updated_streams}

    def serialize_campaign(self, campaign: Campaign) -> CampaignDetailResponse:
        flows = []
        for flow in sorted(campaign.flows, key=self._flow_display_sort_key):
            offers = [
                {
                    "offer_id": offer.keitaro_offer_id,
                    "name": offer.name,
                    "weight": offer.weight,
                    "position": offer.position,
                    "is_pinned": offer.is_pinned,
                    "pending_action": offer.pending_action,
                    "stats": offer.stats or {},
                    "trends": offer.trends or {},
                }
                for offer in self._flow2_offers(flow)
            ]
            flows.append(
                {
                    "id": flow.id,
                    "keitaro_flow_id": flow.keitaro_flow_id,
                    "name": flow.name,
                    "position": flow.position,
                    "type": flow.kind,
                    "redirect_url": flow.redirect_url,
                    "geo_codes": flow.geo_codes,
                    "offers": offers,
                    "status": flow.status,
                    "pending_action": flow.pending_action,
                    "metrics": flow.metrics or {},
                    "has_pending_changes": self._flow_has_pending_changes(flow),
                }
            )
        stats = self._campaign_stats(campaign)
        return CampaignDetailResponse.model_validate(
            {
                "id": campaign.id,
                "keitaro_campaign_id": campaign.keitaro_campaign_id,
                "name": campaign.name,
                "alias": campaign.alias,
                "campaign_url": campaign.campaign_url,
                "keitaro_admin_url": self._keitaro_admin_url(campaign),
                "geo_codes": campaign.geo_codes,
                "status": self._campaign_status(campaign),
                "pending_action": campaign.pending_action,
                "metrics": campaign.metrics or {},
                "flows": flows,
                "stats": stats,
            }
        )

    def _sync_keitaro_campaign(
        self,
        kt_campaign: KeitaroCampaign,
        campaign: Campaign | None = None,
    ) -> tuple[Campaign, dict[str, int]]:
        counts = {"campaigns_imported": 0, "flows_imported": 0, "offers_imported": 0}
        if campaign is None:
            campaign = self.db.scalar(
                select(Campaign).where(Campaign.keitaro_campaign_id == kt_campaign.id)
            )

        alias = kt_campaign.alias or f"kt-{kt_campaign.id}"
        campaign_payload = kt_campaign.payload or {}
        if campaign is None:
            campaign = Campaign(
                keitaro_campaign_id=kt_campaign.id,
                name=kt_campaign.name or f"Campaign {kt_campaign.id}",
                alias=alias,
                campaign_url=self._build_campaign_url(
                    self._campaign_domain_url(), alias
                ),
                geo_codes=[],
                domain_id=kt_campaign.domain_id,
                domain_url=self._campaign_domain_url(),
                group_id=kt_campaign.group_id,
                traffic_source_id=kt_campaign.traffic_source_id,
                status=kt_campaign.state or "active",
                pending_action=None,
                metrics=self._metrics_from_payload(campaign_payload),
                kt_payload=campaign_payload,
            )
            self.db.add(campaign)
            self.db.flush()
            counts["campaigns_imported"] += 1
        else:
            campaign.name = kt_campaign.name or campaign.name
            campaign.alias = alias
            campaign.campaign_url = self._build_campaign_url(
                self._campaign_domain_url(), alias
            )
            campaign.domain_id = kt_campaign.domain_id or campaign.domain_id
            campaign.group_id = kt_campaign.group_id or campaign.group_id
            campaign.traffic_source_id = (
                kt_campaign.traffic_source_id or campaign.traffic_source_id
            )
            if campaign.pending_action != "delete":
                campaign.status = kt_campaign.state or campaign.status
            campaign.metrics = self._metrics_from_payload(campaign_payload)
            campaign.kt_payload = campaign_payload

        try:
            streams = self.keitaro.get_campaign_streams(kt_campaign.id)
        except KeitaroError as exc:
            raise self._keitaro_to_app_error(exc) from exc

        synced_flow_ids: set[int] = set()
        campaign_geo_codes: list[str] = []
        for index, stream_summary in enumerate(streams, start=1):
            kt_stream = self._hydrate_keitaro_stream(stream_summary)
            synced_flow_ids.add(kt_stream.id)
            flow = self.db.scalar(
                select(Flow).where(
                    Flow.campaign_id == campaign.id,
                    Flow.keitaro_flow_id == kt_stream.id,
                )
            )
            stream_payload = kt_stream.payload or {}
            geo_codes = self._geo_from_stream_filters(kt_stream.filters or [])
            if geo_codes:
                campaign_geo_codes = geo_codes

            if flow is None:
                flow = Flow(
                    campaign_id=campaign.id,
                    keitaro_flow_id=kt_stream.id,
                    name=kt_stream.name or f"Stream {kt_stream.id}",
                    position=kt_stream.position or index,
                    kind=self._kind_from_stream(
                        kt_stream.schema, kt_stream.offers or []
                    ),
                    redirect_url=self._redirect_from_stream(stream_payload),
                    geo_codes=geo_codes,
                    status=kt_stream.state or "active",
                    pending_action=None,
                    metrics=self._metrics_from_payload(stream_payload),
                    kt_payload=stream_payload,
                )
                self.db.add(flow)
                self.db.flush()
                counts["flows_imported"] += 1
            else:
                flow.name = kt_stream.name or flow.name
                flow.position = kt_stream.position or flow.position
                flow.kind = self._kind_from_stream(
                    kt_stream.schema, kt_stream.offers or []
                )
                flow.redirect_url = self._redirect_from_stream(stream_payload)
                flow.geo_codes = geo_codes
                flow.status = kt_stream.state or flow.status
                flow.metrics = self._metrics_from_payload(stream_payload)
                flow.kt_payload = stream_payload

            synced_offer_ids: set[int] = set()
            for offer_index, raw_offer in enumerate(kt_stream.offers or [], start=1):
                offer_id = self._offer_id_from_stream_offer(raw_offer)
                if offer_id is None:
                    continue
                synced_offer_ids.add(offer_id)
                share = self._share_from_stream_offer(raw_offer)
                local_offer = self.db.scalar(
                    select(CampaignOffer).where(
                        CampaignOffer.campaign_id == campaign.id,
                        CampaignOffer.flow_id == flow.id,
                        CampaignOffer.keitaro_offer_id == offer_id,
                    )
                )
                offer_name = self._offer_name_from_stream_offer(raw_offer, offer_id)
                if local_offer is None:
                    local_offer = CampaignOffer(
                        campaign_id=campaign.id,
                        flow_id=flow.id,
                        keitaro_offer_id=offer_id,
                        name=offer_name,
                        weight=share,
                        position=offer_index,
                        is_pinned=False,
                        pending_action=None,
                        stats=self._metrics_from_payload(raw_offer),
                        trends=self._metrics_from_payload(
                            raw_offer.get("trends") or {}
                        ),
                        kt_payload=raw_offer,
                    )
                    flow.offers.append(local_offer)
                    self.db.add(local_offer)
                    counts["offers_imported"] += 1
                elif not self._offer_has_pending_change(local_offer):
                    local_offer.name = offer_name
                    if not local_offer.is_pinned:
                        local_offer.weight = share
                    local_offer.position = offer_index
                    local_offer.pending_action = None
                    local_offer.stats = self._metrics_from_payload(raw_offer)
                    local_offer.trends = self._metrics_from_payload(
                        raw_offer.get("trends") or {}
                    )
                    local_offer.kt_payload = raw_offer

            stale_offers = [
                offer
                for offer in list(flow.offers)
                if offer.keitaro_offer_id not in synced_offer_ids
                and offer.pending_action not in ("add", "restore")
            ]
            for offer in stale_offers:
                self._mark_offer_removed(offer)
            if stale_offers:
                self._recompute_flow_weights(flow)
            elif any(
                self._offer_has_pending_change(offer) or offer.is_pinned
                for offer in flow.offers
            ):
                self._recompute_flow_weights(flow)

        if campaign_geo_codes:
            campaign.geo_codes = campaign_geo_codes

        stale_flows = [
            flow
            for flow in list(campaign.flows)
            if flow.keitaro_flow_id is not None
            and flow.keitaro_flow_id not in synced_flow_ids
        ]
        for flow in stale_flows:
            self.db.delete(flow)
        if stale_flows:
            self.db.flush()
            self.db.expire(campaign, ["flows"])

        return campaign, counts

    def _sync_keitaro_campaign_metadata(
        self,
        kt_campaign: KeitaroCampaign,
    ) -> tuple[Campaign, dict[str, int]]:
        counts = {"campaigns_imported": 0, "flows_imported": 0, "offers_imported": 0}
        campaign = self.db.scalar(
            select(Campaign).where(Campaign.keitaro_campaign_id == kt_campaign.id)
        )
        alias = kt_campaign.alias or f"kt-{kt_campaign.id}"
        campaign_payload = kt_campaign.payload or {}

        if campaign is None:
            campaign = Campaign(
                keitaro_campaign_id=kt_campaign.id,
                name=kt_campaign.name or f"Campaign {kt_campaign.id}",
                alias=alias,
                campaign_url=self._build_campaign_url(
                    self._campaign_domain_url(), alias
                ),
                geo_codes=[],
                domain_id=kt_campaign.domain_id,
                domain_url=self._campaign_domain_url(),
                group_id=kt_campaign.group_id,
                traffic_source_id=kt_campaign.traffic_source_id,
                status=kt_campaign.state or "active",
                pending_action=None,
                metrics=self._metrics_from_payload(campaign_payload),
                kt_payload=campaign_payload,
            )
            self.db.add(campaign)
            self.db.flush()
            counts["campaigns_imported"] += 1
        else:
            campaign.name = kt_campaign.name or campaign.name
            campaign.alias = alias
            campaign.campaign_url = self._build_campaign_url(
                self._campaign_domain_url(), alias
            )
            campaign.domain_id = kt_campaign.domain_id or campaign.domain_id
            campaign.group_id = kt_campaign.group_id or campaign.group_id
            campaign.traffic_source_id = (
                kt_campaign.traffic_source_id or campaign.traffic_source_id
            )
            if campaign.pending_action != "delete":
                campaign.status = kt_campaign.state or campaign.status
            campaign.metrics = self._metrics_from_payload(campaign_payload)
            campaign.kt_payload = campaign_payload

        return campaign, counts

    def _hydrate_keitaro_stream(self, stream: Any) -> Any:
        has_metrics = bool(self._metrics_from_payload(stream.payload or {}))
        if stream.offers and has_metrics:
            return stream

        get_stream = getattr(self.keitaro, "get_stream", None)
        if get_stream is None:
            return stream

        try:
            detailed_stream = get_stream(stream.id)
        except KeitaroError:
            return stream

        merged_payload = {**(stream.payload or {}), **(detailed_stream.payload or {})}
        return KeitaroStream(
            id=detailed_stream.id,
            name=detailed_stream.name or stream.name,
            position=detailed_stream.position or stream.position,
            state=detailed_stream.state or stream.state,
            schema=detailed_stream.schema or stream.schema,
            offers=detailed_stream.offers or stream.offers,
            filters=detailed_stream.filters or stream.filters,
            payload=merged_payload,
        )

    def _refresh_campaign_report_metrics(self, campaign: Campaign) -> None:
        if campaign.keitaro_campaign_id is None:
            return
        payload = {
            "range": {
                "interval": "today",
                "timezone": self.REPORT_TIMEZONE,
            },
            "metrics": [
                "clicks",
                "conversions",
                "revenue",
                "cost",
                "profit",
            ],
            "grouping": ["campaign"],
            "limit": 100,
            "offset": 0,
        }
        try:
            report = self.keitaro.get_report(payload)
        except (AttributeError, KeitaroError):
            return
        metrics = self._metrics_from_report(
            report,
            campaign_name=campaign.name,
            campaign_id=campaign.keitaro_campaign_id,
        )
        if metrics:
            campaign.metrics = {**(campaign.metrics or {}), **metrics}

    def _campaign_list_item(self, campaign: Campaign) -> CampaignListItem:
        return CampaignListItem.model_validate(
            {
                "id": campaign.id,
                "keitaro_campaign_id": campaign.keitaro_campaign_id,
                "name": campaign.name,
                "alias": campaign.alias,
                "campaign_url": campaign.campaign_url,
                "keitaro_admin_url": self._keitaro_admin_url(campaign),
                "geo_codes": campaign.geo_codes,
                "status": self._campaign_status(campaign),
                "pending_action": campaign.pending_action,
                "metrics": campaign.metrics or {},
                "stream_count": len(campaign.flows),
                "has_pending_changes": self._campaign_has_pending_changes(campaign),
                "created_at": campaign.created_at,
                "updated_at": campaign.updated_at,
            }
        )

    def _campaign_status(self, campaign: Campaign) -> str:
        if campaign.pending_action:
            return campaign.status
        if self._campaign_has_pending_changes(campaign):
            return "changed"
        return campaign.status

    def _campaign_has_pending_changes(self, campaign: Campaign) -> bool:
        return any(self._flow_has_pending_changes(flow) for flow in campaign.flows)

    def _flow_has_pending_changes(self, flow: Flow) -> bool:
        return flow.pending_action is not None or any(
            self._offer_has_pending_change(offer) for offer in flow.offers
        )

    def _flow_display_sort_key(self, flow: Flow) -> tuple[bool, int, int]:
        return (self._last_synced_offer_count(flow) == 0, flow.position, flow.id or 0)

    def _last_synced_offer_count(self, flow: Flow) -> int:
        return len(
            [
                offer
                for offer in flow.offers
                if offer.pending_action not in ("add", "restore", "removed")
            ]
        )

    def _get_previous_idempotent_operation(
        self, idempotency_key: str
    ) -> OperationLog | None:
        statement: Select[tuple[OperationLog]] = (
            select(OperationLog)
            .where(
                OperationLog.operation_type == "create_campaign",
                OperationLog.idempotency_key == idempotency_key,
            )
            .order_by(desc(OperationLog.created_at))
        )
        return self.db.scalars(statement).first()

    def _mark_operation_failed(
        self,
        operation: OperationLog,
        error: AppError,
        started_at: float,
        campaign: Campaign | None,
    ) -> None:
        self.db.rollback()
        if campaign is not None:
            campaign.status = "failed"
            campaign.error_message = error.message
            self.db.add(campaign)
        operation.status = "failed"
        operation.error_code = error.code
        operation.error_message = error.message
        operation.duration_seconds = time.monotonic() - started_at
        self.db.add(operation)
        self.db.commit()

    def _try_archive_partial_campaign(
        self, keitaro_campaign_id: int | None, app_error: AppError
    ) -> None:
        if keitaro_campaign_id is None:
            return
        try:
            self.keitaro.archive_campaign(keitaro_campaign_id)
        except KeitaroError:
            app_error.message = f"{app_error.message}. Keitaro campaign {keitaro_campaign_id} may remain partially created."

    def _get_campaign_or_404(self, campaign_id: int) -> Campaign:
        campaign = self.db.get(Campaign, campaign_id)
        if campaign is None:
            raise AppError(404, "CAMPAIGN_NOT_FOUND", "Campaign was not found")
        return campaign

    @staticmethod
    def _get_flow_or_404(campaign: Campaign, flow_id: int) -> Flow:
        flow = next((item for item in campaign.flows if item.id == flow_id), None)
        if flow is None:
            raise AppError(404, "FLOW_NOT_FOUND", "Flow was not found")
        return flow

    @staticmethod
    def _get_flow2_or_404(campaign: Campaign) -> Flow:
        flow = next(
            (item for item in campaign.flows if item.kind == "offers_fallback"), None
        )
        if flow is None or flow.keitaro_flow_id is None:
            raise AppError(424, "KEITARO_FLOW_NOT_FOUND", "Flow 2 was not found")
        return flow

    @staticmethod
    def _flow2_offers(flow2: Flow) -> list[CampaignOffer]:
        return sorted(
            flow2.offers,
            key=lambda item: (
                item.pending_action in CampaignService.INACTIVE_OFFER_ACTIONS,
                item.position,
                item.id or 0,
            ),
        )

    def _recompute_flow_weights(self, flow: Flow) -> None:
        ordered = sorted(flow.offers, key=lambda item: (item.position, item.id or 0))
        active = [offer for offer in ordered if not self._offer_is_inactive(offer)]
        inactive = [offer for offer in ordered if self._offer_is_inactive(offer)]
        if not active:
            for index, offer in enumerate(inactive, start=1):
                offer.position = index
                offer.weight = 0
                offer.is_pinned = False
            return

        pinned_total = sum(
            max(0, min(100, offer.weight)) for offer in active if offer.is_pinned
        )
        unpinned = [offer for offer in active if not offer.is_pinned]
        if unpinned:
            remaining_weight = max(0, 100 - pinned_total)
            weights = self._distribute_weight_total(remaining_weight, len(unpinned))
            for index, offer in enumerate(unpinned):
                offer.weight = weights[index]

        for index, offer in enumerate(active):
            offer.position = index + 1
        for index, offer in enumerate(inactive, start=len(active) + 1):
            offer.position = index
            offer.weight = 0
            offer.is_pinned = False

    def _assert_keitaro_flow_exists(self, campaign: Campaign, flow2: Flow) -> None:
        streams = self.keitaro.get_campaign_streams(campaign.keitaro_campaign_id)
        if not any(stream.id == flow2.keitaro_flow_id for stream in streams):
            raise AppError(
                424, "KEITARO_FLOW_NOT_FOUND", "Flow 2 was not found in Keitaro"
            )

    @staticmethod
    def _weighted_offer_payload(offers: list[OfferWeightInput]) -> list[dict[str, Any]]:
        weights = distribute_weights(len(offers))
        return [
            {"offer_id": offer.offer_id, "name": offer.name, "weight": weights[index]}
            for index, offer in enumerate(offers)
        ]

    @staticmethod
    def _weighted_offer_payload_from_rows(
        offers: list[CampaignOffer],
    ) -> list[dict[str, Any]]:
        return [
            {
                "offer_id": offer.keitaro_offer_id,
                "name": offer.name,
                "weight": offer.weight,
            }
            for offer in offers
        ]

    @staticmethod
    def _distribute_weight_total(total: int, count: int) -> list[int]:
        if count < 1:
            return []
        base = total // count
        remainder = total - base * count
        return [base + (1 if index < remainder else 0) for index in range(count)]

    @classmethod
    def _offer_is_inactive(cls, offer: CampaignOffer) -> bool:
        return offer.pending_action in cls.INACTIVE_OFFER_ACTIONS

    @classmethod
    def _offer_has_pending_change(cls, offer: CampaignOffer) -> bool:
        return offer.pending_action in cls.PENDING_OFFER_ACTIONS

    @staticmethod
    def _mark_offer_removed(offer: CampaignOffer) -> None:
        offer.pending_action = "removed"
        offer.weight = 0
        offer.is_pinned = False
        offer.stats = {"redirects": 0}
        offer.trends = {}

    def _stream_offers_update_payload(
        self,
        campaign: Campaign,
        flow: Flow,
        offers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if campaign.keitaro_campaign_id is None:
            raise AppError(
                424, "KEITARO_CAMPAIGN_NOT_FOUND", "Campaign is not linked to Keitaro"
            )

        offer_rows = [
            {"offer_id": offer["offer_id"], "share": offer["weight"]}
            for offer in offers
        ]
        if isinstance(flow.kt_payload, dict) and flow.kt_payload:
            payload = dict(flow.kt_payload)
            payload["campaign_id"] = campaign.keitaro_campaign_id
            payload["name"] = flow.name
            payload["position"] = flow.position
            payload["state"] = flow.status or payload.get("state") or "active"
            payload["schema"] = payload.get("schema") or "offers"
            payload["offers"] = offer_rows
            action_payload = payload.get("action_payload")
            if isinstance(action_payload, dict):
                payload["action_payload"] = {**action_payload, "offers": offer_rows}
            return payload

        return offers_stream_update_payload(
            campaign_id=campaign.keitaro_campaign_id,
            name=flow.name,
            position=flow.position,
            offers=offers,
        )

    def _offers_update_response(
        self, campaign: Campaign, flow2: Flow
    ) -> dict[str, Any]:
        return {
            "campaign_id": campaign.id,
            "flow_id": flow2.id,
            "offers": [
                {
                    "offer_id": offer.keitaro_offer_id,
                    "name": offer.name,
                    "weight": offer.weight,
                    "position": offer.position,
                    "is_pinned": offer.is_pinned,
                    "pending_action": offer.pending_action,
                    "stats": offer.stats or {},
                    "trends": offer.trends or {},
                }
                for offer in self._flow2_offers(flow2)
            ],
        }

    @staticmethod
    def _metrics_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        metrics: dict[str, Any] = {}
        aliases = {
            "clicks": ("clicks", "click_count", "clicks_count", "visits", "hits"),
            "unique_clicks": (
                "unique_clicks",
                "uniques",
                "unique",
                "uc",
                "unique_count",
                "unique_visitors",
                "unique_visits",
            ),
            "bots": ("bots", "bot_count", "bot_clicks", "filtered_clicks"),
            "conversions": ("conversions", "conversion", "sales", "leads", "actions"),
            "revenue": ("revenue", "income", "profit_confirmed", "sales_amount"),
            "cost": ("cost", "costs", "campaign_cost"),
            "profit": ("profit",),
            "cr": ("cr", "conversion_rate", "conversion_rate_percent"),
            "roi": ("roi",),
        }
        for target_key, source_keys in aliases.items():
            for source_key in source_keys:
                value = CampaignService._get_payload_value(payload, source_key)
                if value is not None:
                    metrics[target_key] = value
                    break

        for nested_key in (
            "metrics",
            "stats",
            "stat",
            "summary",
            "totals",
            "total",
            "values",
        ):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                metrics.update(CampaignService._metrics_from_payload(nested))
        return metrics

    @classmethod
    def _metrics_from_report(
        cls,
        payload: dict[str, Any],
        *,
        campaign_name: str | None = None,
        campaign_id: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        selected_row = cls._select_report_row(
            payload, campaign_name=campaign_name, campaign_id=campaign_id
        )
        if selected_row is not None:
            return cls._metrics_from_payload(selected_row)

        metrics: dict[str, Any] = {}
        for candidate in cls._iter_report_metric_candidates(payload):
            for key, value in candidate.items():
                if cls._metric_has_value(value) or not cls._metric_has_value(
                    metrics.get(key)
                ):
                    metrics[key] = value
        return metrics

    @classmethod
    def _iter_report_metric_candidates(cls, value: Any) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if isinstance(value, dict):
            metrics = cls._metrics_from_payload(value)
            if metrics:
                candidates.append(metrics)
            for nested in value.values():
                candidates.extend(cls._iter_report_metric_candidates(nested))
        elif isinstance(value, list):
            for item in value:
                candidates.extend(cls._iter_report_metric_candidates(item))
        return candidates

    @classmethod
    def _select_report_row(
        cls,
        payload: dict[str, Any],
        *,
        campaign_name: str | None,
        campaign_id: int | None,
    ) -> dict[str, Any] | None:
        rows = cls._report_rows(payload)
        if not rows:
            return None
        if campaign_id is not None:
            for row in rows:
                value = row.get("campaign_id")
                if value not in (None, "") and cls._int_metric(value) == campaign_id:
                    return row
        if campaign_name:
            normalized_name = campaign_name.strip().lower()
            for row in rows:
                value = (
                    row.get("campaign") or row.get("campaign_name") or row.get("name")
                )
                if isinstance(value, str) and value.strip().lower() == normalized_name:
                    return row
        if len(rows) == 1:
            return rows[0]
        return None

    @classmethod
    def _report_rows(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            for key in ("rows", "items", "data"):
                nested = value.get(key)
                rows = cls._report_rows(nested)
                if rows:
                    return rows
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _stats_response_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
        clicks = CampaignService._int_metric(metrics.get("clicks"))
        conversions = CampaignService._int_metric(
            metrics.get("conversions") or metrics.get("sales")
        )
        cr = CampaignService._float_metric(metrics.get("cr"))
        if not cr and clicks:
            cr = conversions / clicks * 100
        return {
            "clicks": clicks,
            "unique_clicks": CampaignService._int_metric(
                metrics.get("unique_clicks") or metrics.get("uniques")
            ),
            "bots": CampaignService._int_metric(metrics.get("bots")),
            "conversions": conversions,
            "revenue": CampaignService._float_metric(metrics.get("revenue")),
            "cost": CampaignService._float_metric(metrics.get("cost")),
            "profit": CampaignService._float_metric(metrics.get("profit")),
            "cr": cr,
        }

    def _campaign_stats(self, campaign: Campaign) -> dict[str, Any]:
        metrics = dict(campaign.metrics or {})
        if any(
            metrics.get(key)
            for key in (
                "clicks",
                "unique_clicks",
                "bots",
                "conversions",
                "revenue",
                "cost",
                "profit",
                "cr",
            )
        ):
            return self._stats_response_from_metrics(metrics)

        for flow in campaign.flows:
            flow_metrics = flow.metrics or {}
            metrics["clicks"] = self._int_metric(
                metrics.get("clicks")
            ) + self._int_metric(flow_metrics.get("clicks"))
            metrics["unique_clicks"] = self._int_metric(
                metrics.get("unique_clicks")
            ) + self._int_metric(
                flow_metrics.get("unique_clicks") or flow_metrics.get("uniques")
            )
            metrics["bots"] = self._int_metric(metrics.get("bots")) + self._int_metric(
                flow_metrics.get("bots")
            )
            metrics["conversions"] = self._int_metric(
                metrics.get("conversions")
            ) + self._int_metric(
                flow_metrics.get("conversions") or flow_metrics.get("sales")
            )
            metrics["revenue"] = self._float_metric(
                metrics.get("revenue")
            ) + self._float_metric(flow_metrics.get("revenue"))
            metrics["cost"] = self._float_metric(
                metrics.get("cost")
            ) + self._float_metric(flow_metrics.get("cost"))
            metrics["profit"] = self._float_metric(
                metrics.get("profit")
            ) + self._float_metric(flow_metrics.get("profit"))
        return self._stats_response_from_metrics(metrics)

    @staticmethod
    def _int_metric(value: Any) -> int:
        if value in (None, ""):
            return 0
        if isinstance(value, str):
            value = (
                value.replace(",", "")
                .replace(" ", "")
                .replace("%", "")
                .replace("$", "")
            )
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float_metric(value: Any) -> float:
        if value in (None, ""):
            return 0
        if isinstance(value, str):
            value = (
                value.replace(",", "")
                .replace(" ", "")
                .replace("%", "")
                .replace("$", "")
            )
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _get_payload_value(payload: dict[str, Any], source_key: str) -> Any:
        value = payload.get(source_key)
        if value is not None:
            return value
        normalized_source = CampaignService._normalize_metric_key(source_key)
        for key, candidate in payload.items():
            if CampaignService._normalize_metric_key(str(key)) == normalized_source:
                return candidate
        return None

    @staticmethod
    def _normalize_metric_key(key: str) -> str:
        return "".join(character for character in key.lower() if character.isalnum())

    @staticmethod
    def _metric_has_value(value: Any) -> bool:
        if value in (None, ""):
            return False
        if isinstance(value, str):
            value = (
                value.replace(",", "")
                .replace(" ", "")
                .replace("%", "")
                .replace("$", "")
            )
        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _geo_from_stream_filters(filters: list[dict[str, Any]]) -> list[str]:
        for item in filters:
            name = str(item.get("name") or "").lower()
            if name == "country":
                payload = item.get("payload") or item.get("values") or []
                if isinstance(payload, list):
                    return [str(value).upper() for value in payload]
        return []

    @staticmethod
    def _kind_from_stream(schema: str | None, offers: list[dict[str, Any]]) -> str:
        if offers or schema == "offers":
            return "offers_fallback"
        return "geo_redirect"

    @staticmethod
    def _redirect_from_stream(payload: dict[str, Any]) -> str | None:
        for key in ("redirect_url", "url", "action_payload"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _offer_id_from_stream_offer(raw_offer: dict[str, Any]) -> int | None:
        offer = raw_offer.get("offer")
        if isinstance(offer, dict) and offer.get("id") is not None:
            return int(offer["id"])
        for key in ("offer_id", "offerId", "offerID", "keitaro_offer_id"):
            value = raw_offer.get(key)
            if value not in (None, ""):
                return int(value)
        if raw_offer.get("name") or raw_offer.get("title"):
            value = raw_offer.get("id")
            if value not in (None, ""):
                return int(value)
        return None

    def _offer_name_from_stream_offer(
        self, raw_offer: dict[str, Any], offer_id: int
    ) -> str:
        nested_offer = raw_offer.get("offer")
        if isinstance(nested_offer, dict):
            nested_name = nested_offer.get("name") or nested_offer.get("title")
            if nested_name:
                return str(nested_name)

        offer_name = str(
            raw_offer.get("name") or raw_offer.get("title") or f"Offer {offer_id}"
        )
        if offer_name != f"Offer {offer_id}":
            return offer_name

        try:
            return self.keitaro.get_offer(offer_id).name
        except KeitaroError:
            return offer_name

    @staticmethod
    def _share_from_stream_offer(raw_offer: dict[str, Any]) -> int:
        for key in ("share", "weight", "percent", "percentage"):
            value = raw_offer.get(key)
            if value not in (None, ""):
                if isinstance(value, str):
                    value = value.strip().rstrip("%")
                return int(float(value))
        return 100

    def _generate_unique_alias(self) -> str:
        for _ in range(10):
            alias = generate_alias()
            if not self._alias_exists(alias):
                return alias
        raise AppError(
            409,
            "CAMPAIGN_ALIAS_ALREADY_EXISTS",
            "Could not generate a unique campaign alias",
        )

    def _alias_exists(self, alias: str) -> bool:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(Campaign)
                .where(Campaign.alias == alias)
            )
            > 0
        )

    def _campaign_domain_url(self) -> str:
        return (
            self.settings.keitaro_campaign_domain_url or self.settings.keitaro_base_url
        )

    def _keitaro_admin_url(self, campaign: Campaign) -> str | None:
        if campaign.keitaro_campaign_id is None:
            return None
        return f"{self.settings.keitaro_base_url.rstrip('/')}/admin/campaigns/{campaign.keitaro_campaign_id}"

    @staticmethod
    def _build_campaign_url(domain_url: str, alias: str) -> str:
        return f"{domain_url.rstrip('/')}/{alias}"

    @staticmethod
    def _offer_to_dict(offer: KeitaroOffer) -> dict[str, Any]:
        return {
            "id": offer.id,
            "name": offer.name,
            "country": offer.country,
            "state": offer.state,
            "affiliate_network": offer.affiliate_network,
            "url": offer.url,
        }

    @staticmethod
    def _keitaro_to_app_error(exc: KeitaroError) -> AppError:
        if exc.code == "KEITARO_TIMEOUT":
            return AppError(503, "KEITARO_TIMEOUT", str(exc), exc.details)
        if exc.code == "KEITARO_UNAVAILABLE":
            return AppError(503, "KEITARO_UNAVAILABLE", str(exc), exc.details)
        if exc.code == "KEITARO_BAD_RESPONSE":
            return AppError(502, "KEITARO_BAD_RESPONSE", str(exc), exc.details)
        if exc.code == "KEITARO_REFERENCE_CONFLICT":
            return AppError(409, "KEITARO_REFERENCE_CONFLICT", str(exc), exc.details)
        if exc.code == "KEITARO_REFERENCE_NOT_FOUND":
            return AppError(424, "KEITARO_REFERENCE_NOT_FOUND", str(exc), exc.details)

        mapping = {
            401: (403, "KEITARO_FORBIDDEN"),
            403: (403, "KEITARO_FORBIDDEN"),
            404: (424, "KEITARO_NOT_FOUND"),
            422: (422, "KEITARO_VALIDATION_ERROR"),
            423: (424, "KEITARO_LOCKED"),
            500: (502, "KEITARO_INTERNAL_ERROR"),
        }
        status_code, code = mapping.get(
            exc.http_status or 0, (502, "KEITARO_BAD_RESPONSE")
        )
        return AppError(status_code, code, str(exc), exc.details)
