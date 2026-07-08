from typing import Any


def campaign_payload(
    *,
    name: str,
    alias: str,
    domain_id: int | None = None,
    group_id: int | None = None,
    traffic_source_id: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "alias": alias,
        "type": "position",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
    }
    if domain_id is not None:
        payload["domain_id"] = domain_id
    if group_id is not None:
        payload["group_id"] = group_id
    if traffic_source_id is not None:
        payload["traffic_source_id"] = traffic_source_id
    return payload


def flow_1_payload(*, campaign_id: int, geo_codes: list[str], redirect_url: str) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "name": "Flow 1",
        "type": "regular",
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": "http",
        "action_payload": redirect_url,
        "filters": [
            {
                "name": "country",
                "mode": "accept",
                "payload": geo_codes,
            }
        ],
    }


def flow_2_payload(*, campaign_id: int, offers: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "name": "Flow 2",
        "type": "regular",
        "position": 2,
        "state": "active",
        "schema": "landings",
        "action_type": "http",
        "action_payload": "",
        "offer_selection": "before_click",
        "filters": [],
        "offers": [{"offer_id": offer["offer_id"], "share": offer["weight"]} for offer in offers],
    }


def offers_stream_update_payload(
    *,
    campaign_id: int,
    name: str,
    position: int,
    offers: list[dict[str, int]],
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "name": name,
        "type": "regular",
        "position": position,
        "state": "active",
        "schema": "landings",
        "action_type": "http",
        "action_payload": "",
        "offer_selection": "before_click",
        "filters": [],
        "offers": [{"offer_id": offer["offer_id"], "share": offer["weight"]} for offer in offers],
    }
