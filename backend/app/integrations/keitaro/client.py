from dataclasses import dataclass
import json
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class KeitaroOffer:
    id: int
    name: str
    country: str | None = None
    state: str | None = None
    affiliate_network: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class KeitaroCampaign:
    id: int
    name: str | None = None
    alias: str | None = None
    state: str | None = None
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class KeitaroStream:
    id: int
    name: str | None = None
    position: int | None = None
    state: str | None = None
    schema: str | None = None
    offers: list[dict[str, Any]] | None = None
    filters: list[dict[str, Any]] | None = None
    payload: dict[str, Any] | None = None


class KeitaroError(Exception):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.http_status = http_status
        self.code = code
        self.details = details
        super().__init__(message)


class KeitaroClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.keitaro_base_url.rstrip("/")
        self.timeout = 20

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}/admin_api/v1{path}"
        headers = kwargs.pop("headers", {})
        headers["Api-Key"] = self.settings.keitaro_api_key
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise KeitaroError("Keitaro request timed out", code="KEITARO_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise KeitaroError("Keitaro is unavailable", code="KEITARO_UNAVAILABLE") from exc

        if response.status_code >= 400:
            details = self._safe_json(response)
            raise KeitaroError(
                self._message_for_status(response.status_code),
                http_status=response.status_code,
                details=details if isinstance(details, dict) else None,
            )

        if response.status_code == 204 or not response.content:
            return None
        return self._safe_json(response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"body": response.text[:500]}

    @staticmethod
    def _message_for_status(status_code: int) -> str:
        return {
            401: "Keitaro authorization failed",
            403: "Keitaro access is forbidden",
            404: "Keitaro resource was not found",
            423: "Keitaro resource is locked",
            422: "Keitaro rejected payload",
            500: "Keitaro internal error",
        }.get(status_code, "Keitaro returned an error")

    @staticmethod
    def _items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("items", "rows", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _parse_id(payload: dict[str, Any]) -> int:
        for key in ("id", "stream_id", "campaign_id"):
            value = payload.get(key)
            if value is not None:
                return int(value)
        raise KeitaroError("Keitaro response does not contain id", code="KEITARO_BAD_RESPONSE")

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _offer_from_payload(payload: dict[str, Any]) -> KeitaroOffer:
        return KeitaroOffer(
            id=int(payload["id"]),
            name=str(payload.get("name") or payload.get("title") or payload["id"]),
            country=payload.get("country"),
            state=payload.get("state"),
            affiliate_network=payload.get("affiliate_network") or payload.get("network"),
            url=payload.get("url") or payload.get("action_payload"),
        )

    def get_offer(self, offer_id: int) -> KeitaroOffer:
        payload = self._request("GET", f"/offers/{offer_id}")
        if not isinstance(payload, dict) or "id" not in payload:
            raise KeitaroError("Unexpected offer response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return self._offer_from_payload(payload)

    def list_campaigns(self) -> list[KeitaroCampaign]:
        payload = self._request("GET", "/campaigns")
        return [self._campaign_from_payload(item) for item in self._items(payload) if "id" in item]

    def get_campaign(self, campaign_id: int) -> KeitaroCampaign:
        payload = self._request("GET", f"/campaigns/{campaign_id}")
        if not isinstance(payload, dict) or "id" not in payload:
            raise KeitaroError("Unexpected campaign response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return self._campaign_from_payload(payload)

    def search_offers(self, query: str, limit: int) -> list[KeitaroOffer]:
        payload = self._request("GET", "/offers", params={"search": query, "limit": limit})
        query_lower = query.lower()
        offers = [self._offer_from_payload(item) for item in self._items(payload) if "id" in item]
        filtered = [
            offer
            for offer in offers
            if query_lower in str(offer.id).lower()
            or query_lower in offer.name.lower()
            or query_lower in (offer.country or "").lower()
            or query_lower in (offer.affiliate_network or "").lower()
            or query_lower in (offer.state or "").lower()
        ]
        return filtered[:limit]

    def create_campaign(self, payload: dict[str, Any]) -> KeitaroCampaign:
        response = self._request("POST", "/campaigns", json=payload)
        if not isinstance(response, dict):
            raise KeitaroError("Unexpected campaign response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return KeitaroCampaign(
            id=self._parse_id(response),
            name=response.get("name"),
            alias=response.get("alias"),
            state=response.get("state"),
            domain_id=self._optional_int(response.get("domain_id")),
            group_id=self._optional_int(response.get("group_id")),
            traffic_source_id=self._optional_int(response.get("traffic_source_id")),
            payload=response,
        )

    def archive_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    def get_campaign_streams(self, campaign_id: int) -> list[KeitaroStream]:
        response = self._request("GET", f"/campaigns/{campaign_id}/streams")
        return [self._stream_from_payload(item) for item in self._items(response)]

    def get_stream(self, stream_id: int) -> KeitaroStream:
        response = self._request("GET", f"/streams/{stream_id}")
        if not isinstance(response, dict) or "id" not in response:
            raise KeitaroError("Unexpected stream response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return self._stream_from_payload(response)

    def create_stream(self, payload: dict[str, Any]) -> KeitaroStream:
        response = self._request("POST", "/streams", json=payload)
        if not isinstance(response, dict):
            raise KeitaroError("Unexpected stream response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return KeitaroStream(id=self._parse_id(response), name=response.get("name"))

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> KeitaroStream:
        response = self._request("PUT", f"/streams/{stream_id}", json=payload)
        if response is None:
            return KeitaroStream(id=stream_id)
        if not isinstance(response, dict):
            raise KeitaroError("Unexpected stream response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return KeitaroStream(id=self._parse_id(response), name=response.get("name"))

    def get_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/report/build", json=payload)
        if not isinstance(response, dict):
            raise KeitaroError("Unexpected report response from Keitaro", code="KEITARO_BAD_RESPONSE")
        return response

    def _campaign_from_payload(self, payload: dict[str, Any]) -> KeitaroCampaign:
        return KeitaroCampaign(
            id=self._parse_id(payload),
            name=payload.get("name"),
            alias=payload.get("alias"),
            state=payload.get("state"),
            domain_id=self._optional_int(payload.get("domain_id")),
            group_id=self._optional_int(payload.get("group_id") or payload.get("group") and payload["group"].get("id")),
            traffic_source_id=self._optional_int(
                payload.get("traffic_source_id") or payload.get("traffic_source") and payload["traffic_source"].get("id")
            ),
            payload=payload,
        )

    def _stream_from_payload(self, payload: dict[str, Any]) -> KeitaroStream:
        offers = self._extract_stream_offers(payload)
        filters = payload.get("filters")
        if not isinstance(filters, list):
            filters = []
        return KeitaroStream(
            id=self._parse_id(payload),
            name=payload.get("name"),
            position=self._optional_int(payload.get("position")),
            state=payload.get("state"),
            schema=payload.get("schema") or payload.get("action_type") or payload.get("action"),
            offers=[item for item in offers if isinstance(item, dict)],
            filters=[item for item in filters if isinstance(item, dict)],
            payload=payload,
        )

    @classmethod
    def _extract_stream_offers(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            payload.get("offers"),
            payload.get("action_payload"),
            payload.get("action_options"),
            payload.get("payload"),
            payload.get("settings"),
        ]
        for candidate in candidates:
            offers = cls._offers_from_candidate(candidate)
            if offers:
                return offers
        return []

    @classmethod
    def _offers_from_candidate(cls, candidate: Any) -> list[dict[str, Any]]:
        candidate = cls._decode_json_candidate(candidate)
        if isinstance(candidate, list):
            rows = [item for item in candidate if isinstance(item, dict)]
            offer_rows = [item for item in rows if cls._looks_like_offer_row(item)]
            if offer_rows:
                return offer_rows
            for item in rows:
                nested = cls._offers_from_candidate(item)
                if nested:
                    return nested
        if isinstance(candidate, dict):
            if cls._looks_like_offer_row(candidate):
                return [candidate]
            for key in ("offers", "items", "rows", "data", "paths", "payload", "action_payload"):
                nested = cls._offers_from_candidate(candidate.get(key))
                if nested:
                    return nested
        return []

    @staticmethod
    def _decode_json_candidate(candidate: Any) -> Any:
        if not isinstance(candidate, str):
            return candidate
        stripped = candidate.strip()
        if not stripped or stripped[0] not in "[{":
            return candidate
        try:
            return json.loads(stripped)
        except ValueError:
            return candidate

    @staticmethod
    def _looks_like_offer_row(item: dict[str, Any]) -> bool:
        if any(key in item for key in ("offer_id", "offer", "share", "weight")):
            return True
        return item.get("id") is not None and any(key in item for key in ("name", "title"))
