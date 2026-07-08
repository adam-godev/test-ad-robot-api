from fastapi.testclient import TestClient

from app.integrations.keitaro.client import KeitaroCampaign, KeitaroError, KeitaroStream


def flow_by_name(payload: dict, name: str) -> dict:
    return next(flow for flow in payload["flows"] if flow["name"] == name)


def flow_with_offer(payload: dict, offer_id: int) -> dict:
    return next(flow for flow in payload["flows"] if any(offer["offer_id"] == offer_id for offer in flow["offers"]))


def test_successful_campaign_creation_creates_campaign_and_two_flows(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    response = client.post("/api/campaigns", json=create_payload, headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "campaign 2"
    assert body["campaign_url"] == "https://tracker.test/wVqN1R"
    assert body["keitaro_admin_url"] == "https://keitaro.test/admin/#!/campaigns/101"
    assert body["geo_codes"] == ["AU"]
    assert [flow["name"] for flow in body["flows"]] == ["Flow 2", "Flow 1"]
    assert flow_by_name(body, "Flow 1")["redirect_url"] == "https://google.com"
    assert flow_by_name(body, "Flow 2")["offers"][0]["weight"] == 100
    assert fake_keitaro.campaign_payloads[0]["alias"] == "wVqN1R"
    assert fake_keitaro.campaign_payloads[0]["domain_id"] == 11
    assert fake_keitaro.campaign_payloads[0]["group_id"] == 22
    assert fake_keitaro.campaign_payloads[0]["traffic_source_id"] == 33
    assert fake_keitaro.stream_payloads[0]["filters"][0]["payload"] == ["AU"]
    assert "operator" not in fake_keitaro.stream_payloads[0]["filters"][0]
    assert fake_keitaro.stream_payloads[0]["action_type"] == "http"
    assert fake_keitaro.stream_payloads[0]["action_payload"] == "https://google.com"
    assert "redirect_url" not in fake_keitaro.stream_payloads[0]
    assert fake_keitaro.stream_payloads[1]["schema"] == "landings"
    assert fake_keitaro.stream_payloads[1]["action_type"] == "http"
    assert fake_keitaro.stream_payloads[1]["action_payload"] == ""
    assert fake_keitaro.stream_payloads[1]["offer_selection"] == "before_click"
    assert fake_keitaro.stream_payloads[1]["offers"] == [{"offer_id": 3749, "share": 100}]


def test_campaign_creation_accepts_multiple_geo_codes(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    payload = {**create_payload, "geo_codes": ["AU", "RO"]}

    response = client.post("/api/campaigns", json=payload, headers=auth_headers)

    assert response.status_code == 201
    assert response.json()["geo_codes"] == ["AU", "RO"]
    assert fake_keitaro.stream_payloads[0]["filters"][0]["payload"] == ["AU", "RO"]


def test_keitaro_401_is_returned_as_forbidden(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    fake_keitaro.raise_on_create_campaign = KeitaroError("Unauthorized", http_status=401)

    response = client.post("/api/campaigns", json=create_payload, headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "KEITARO_FORBIDDEN"


def test_keitaro_423_is_returned_as_locked_dependency(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    fake_keitaro.raise_on_create_campaign = KeitaroError("Keitaro resource is locked", http_status=423)

    response = client.post("/api/campaigns", json=create_payload, headers=auth_headers)

    assert response.status_code == 424
    assert response.json()["error"]["code"] == "KEITARO_LOCKED"


def test_flow_1_422_archives_created_campaign(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    fake_keitaro.raise_on_stream_number = (1, KeitaroError("Invalid country filter payload", http_status=422))

    response = client.post("/api/campaigns", json=create_payload, headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "KEITARO_VALIDATION_ERROR"
    assert fake_keitaro.archived_campaigns == [101]


def test_campaign_detail_refresh_loads_stats_from_keitaro_report_rows(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    payload = {**create_payload, "name": "Google Ads Fitness App Split"}
    created = client.post("/api/campaigns", json=payload, headers=auth_headers)
    campaign_id = created.json()["id"]
    fake_keitaro.report_payload = {
        "rows": [
            {
                "campaign": "Google Ads Fitness App Split",
                "clicks": 15134,
                "conversions": 2276,
                "revenue": 1151.92,
                "cost": 142.69,
                "profit": 1009.23,
            },
            {
                "campaign": "Meta Ads Food Delivery Promo",
                "clicks": 14986,
                "conversions": 2239,
                "revenue": 1126.68,
                "cost": 136.9692,
                "profit": 989.71,
            },
        ],
        "total": 2,
    }

    response = client.get(f"/api/campaigns/{campaign_id}?refresh=true", headers=auth_headers)

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["clicks"] == 15134
    assert stats["conversions"] == 2276
    assert stats["revenue"] == 1151.92
    assert stats["cost"] == 142.69
    assert stats["profit"] == 1009.23
    assert fake_keitaro.report_requests[-1] == {
        "range": {"interval": "today", "timezone": "Europe/Berlin"},
        "metrics": ["clicks", "conversions", "revenue", "cost", "profit"],
        "grouping": ["campaign"],
        "limit": 100,
        "offset": 0,
    }


def test_campaign_detail_without_refresh_uses_local_state(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    campaign_id = created.json()["id"]
    fake_keitaro.report_payload = {"rows": [{"campaign": "campaign 2", "clicks": 99}]}

    response = client.get(f"/api/campaigns/{campaign_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["stats"]["clicks"] == 0
    assert fake_keitaro.report_requests == []


def test_fetch_from_keitaro_imports_campaign_list_without_stream_contents(
    client: TestClient,
    auth_headers: dict[str, str],
    fake_keitaro,
) -> None:
    fake_keitaro.campaigns[501] = KeitaroCampaign(
        id=501,
        name="Imported shell campaign",
        alias="imported-shell",
        state="active",
        payload={"id": 501, "name": "Imported shell campaign", "alias": "imported-shell"},
    )
    fake_keitaro.streams.append(
        KeitaroStream(
            id=701,
            name="Should not load from list fetch",
            position=1,
            state="active",
            schema="offers",
            offers=[{"offer_id": 3749, "share": 100}],
            payload={"id": 701, "name": "Should not load from list fetch", "offers": [{"offer_id": 3749, "share": 100}]},
        )
    )

    fetched = client.post("/api/campaigns/fetch-from-kt", headers=auth_headers)
    listed = client.get("/api/campaigns", headers=auth_headers)

    assert fetched.status_code == 200
    assert fetched.json() == {"campaigns_imported": 1, "flows_imported": 0, "offers_imported": 0}
    assert fake_keitaro.campaign_stream_requests == []
    assert fake_keitaro.report_requests == []
    item = listed.json()["items"][0]
    assert item["name"] == "Imported shell campaign"
    assert item["stream_count"] is None


def test_campaign_list_shows_stream_count_after_detail_refresh(
    client: TestClient,
    auth_headers: dict[str, str],
    fake_keitaro,
) -> None:
    fake_keitaro.campaigns[501] = KeitaroCampaign(
        id=501,
        name="Imported shell campaign",
        alias="imported-shell",
        state="active",
        payload={"id": 501, "name": "Imported shell campaign", "alias": "imported-shell"},
    )
    fake_keitaro.streams.append(
        KeitaroStream(
            id=701,
            name="Loaded stream",
            position=1,
            state="active",
            schema="redirect",
            offers=[],
            payload={"id": 701, "name": "Loaded stream", "action_payload": "https://google.com"},
        )
    )

    client.post("/api/campaigns/fetch-from-kt", headers=auth_headers)
    before = client.get("/api/campaigns", headers=auth_headers)
    campaign_id = before.json()["items"][0]["id"]
    detail = client.get(f"/api/campaigns/{campaign_id}?refresh=true", headers=auth_headers)
    after = client.get("/api/campaigns", headers=auth_headers)

    assert before.json()["items"][0]["stream_count"] is None
    assert detail.status_code == 200
    assert after.json()["items"][0]["stream_count"] == 1

    client.post("/api/campaigns/fetch-from-kt", headers=auth_headers)
    after_refetch = client.get("/api/campaigns", headers=auth_headers)

    assert after_refetch.json()["items"][0]["stream_count"] == 1


def test_fetch_from_keitaro_updates_existing_campaign_without_duplicate(
    client: TestClient,
    auth_headers: dict[str, str],
    fake_keitaro,
) -> None:
    fake_keitaro.campaigns[501] = KeitaroCampaign(
        id=501,
        name="Imported shell campaign",
        alias="imported-shell",
        state="active",
        payload={"id": 501, "name": "Imported shell campaign", "alias": "imported-shell"},
    )

    first = client.post("/api/campaigns/fetch-from-kt", headers=auth_headers)
    fake_keitaro.campaigns[501] = KeitaroCampaign(
        id=501,
        name="Imported shell campaign updated",
        alias="imported-shell",
        state="active",
        payload={"id": 501, "name": "Imported shell campaign updated", "alias": "imported-shell"},
    )
    second = client.post("/api/campaigns/fetch-from-kt", headers=auth_headers)
    listed = client.get("/api/campaigns", headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {"campaigns_imported": 1, "flows_imported": 0, "offers_imported": 0}
    assert second.status_code == 200
    assert second.json() == {"campaigns_imported": 0, "flows_imported": 0, "offers_imported": 0}
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["name"] == "Imported shell campaign updated"


def test_idempotency_key_returns_previous_result(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    headers = {**auth_headers, "Idempotency-Key": "same-request"}

    first = client.post("/api/campaigns", json=create_payload, headers=headers)
    second = client.post("/api/campaigns", json=create_payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert len(fake_keitaro.campaign_payloads) == 1


def test_duplicate_offer_is_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    campaign_id = created.json()["id"]

    response = client.post(f"/api/campaigns/{campaign_id}/offers", json={"offer_id": 3749}, headers=auth_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OFFER_ALREADY_ATTACHED"


def test_delete_last_offer_updates_keitaro_with_empty_offer_list(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    campaign_id = created.json()["id"]

    response = client.delete(f"/api/campaigns/{campaign_id}/offers/3749", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["offers"] == []
    assert fake_keitaro.updated_streams[-1][1]["offers"] == []


def test_add_offer_updates_keitaro_and_local_database(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    campaign_id = created.json()["id"]

    response = client.post(f"/api/campaigns/{campaign_id}/offers", json={"offer_id": 3717}, headers=auth_headers)

    assert response.status_code == 200
    offers = response.json()["offers"]
    assert [offer["weight"] for offer in offers] == [50, 50]
    assert fake_keitaro.updated_streams[-1][1]["offers"] == [
        {"offer_id": 3749, "share": 50},
        {"offer_id": 3717, "share": 50},
    ]


def test_delete_offer_updates_keitaro_and_local_database(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    campaign_id = created.json()["id"]
    client.post(f"/api/campaigns/{campaign_id}/offers", json={"offer_id": 3717}, headers=auth_headers)

    response = client.delete(f"/api/campaigns/{campaign_id}/offers/3749", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["offers"][0]["offer_id"] == 3717
    assert response.json()["offers"][0]["name"] == "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"
    assert response.json()["offers"][0]["weight"] == 100
    assert fake_keitaro.updated_streams[-1][1]["offers"] == [{"offer_id": 3717, "share": 100}]


def test_stage_add_offer_is_local_until_push(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]

    response = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert fake_keitaro.updated_streams == []
    offers = response.json()["offers"]
    assert [offer["weight"] for offer in offers] == [50, 50]
    assert offers[1]["pending_action"] == "add"

    removed = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3717/stage-remove",
        headers=auth_headers,
    )

    assert removed.status_code == 200
    assert [offer["offer_id"] for offer in removed.json()["offers"]] == [3749]


def test_stage_add_offer_to_empty_stream_is_allowed(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    empty_flow_id = flow_by_name(created_body, "Flow 1")["id"]

    response = client.post(
        f"/api/campaigns/{campaign_id}/streams/{empty_flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert fake_keitaro.updated_streams == []
    assert response.json()["offers"] == [
        {
            "offer_id": 3717,
            "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]",
            "weight": 100,
            "position": 1,
            "is_pinned": False,
            "pending_action": "add",
            "stats": {},
            "trends": {},
        }
    ]


def test_stage_delete_last_offer_can_push_empty_stream(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]

    removed = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3749/stage-remove",
        headers=auth_headers,
    )
    listed = client.get("/api/campaigns", headers=auth_headers)
    pushed = client.post(f"/api/campaigns/{campaign_id}/streams/{flow_id}/push-to-kt", headers=auth_headers)
    reloaded = client.get(f"/api/campaigns/{campaign_id}", headers=auth_headers)

    assert removed.status_code == 200
    staged_offer = removed.json()["offers"][0]
    assert staged_offer["offer_id"] == 3749
    assert staged_offer["pending_action"] == "remove"
    assert staged_offer["weight"] == 0
    assert listed.json()["items"][0]["status"] == "changed"

    assert pushed.status_code == 200
    assert fake_keitaro.updated_streams[-1][1]["offers"] == []
    flow = flow_by_name(reloaded.json(), "Flow 2")
    removed_offer = next(offer for offer in flow["offers"] if offer["offer_id"] == 3749)
    assert removed_offer["pending_action"] == "removed"
    assert flow["has_pending_changes"] is False
    assert reloaded.json()["status"] == "active"


def test_stream_scoped_push_only_updates_target_stream(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow1 = flow_by_name(created_body, "Flow 1")
    flow2 = flow_by_name(created_body, "Flow 2")

    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow1['id']}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow2['id']}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )

    pushed_one = client.post(f"/api/campaigns/{campaign_id}/streams/{flow1['id']}/push-to-kt", headers=auth_headers)
    after_one = client.get(f"/api/campaigns/{campaign_id}", headers=auth_headers).json()

    assert pushed_one.status_code == 200
    assert fake_keitaro.updated_streams[-1][0] == flow1["keitaro_flow_id"]
    assert flow_by_name(after_one, "Flow 1")["has_pending_changes"] is False
    assert flow_by_name(after_one, "Flow 2")["has_pending_changes"] is True
    assert after_one["status"] == "changed"

    pushed_two = client.post(f"/api/campaigns/{campaign_id}/streams/{flow2['id']}/push-to-kt", headers=auth_headers)
    after_two = client.get(f"/api/campaigns/{campaign_id}", headers=auth_headers).json()

    assert pushed_two.status_code == 200
    assert flow_by_name(after_two, "Flow 2")["has_pending_changes"] is False
    assert after_two["status"] == "active"


def test_push_keeps_removed_synced_offer_available_after_reload(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )
    client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)

    removed = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3749/stage-remove",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    pushed = client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)

    assert pushed.status_code == 200
    assert fake_keitaro.updated_streams[-1][1]["offers"] == [{"offer_id": 3717, "share": 100}]

    reloaded = client.get(f"/api/campaigns/{campaign_id}?refresh=false", headers=auth_headers)
    reloaded_flow = flow_by_name(reloaded.json(), "Flow 2")
    offers = reloaded_flow["offers"]
    removed_offer = next(offer for offer in offers if offer["offer_id"] == 3749)
    assert removed_offer["pending_action"] == "removed"
    assert removed_offer["weight"] == 0
    assert reloaded_flow["has_pending_changes"] is False


def test_campaign_detail_fetch_marks_offer_removed_directly_in_keitaro_as_removed(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
    fake_keitaro,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )
    client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)

    flow2_stream = fake_keitaro.streams[1]
    fake_keitaro.streams[1] = type(flow2_stream)(
        id=flow2_stream.id,
        name=flow2_stream.name,
        position=flow2_stream.position,
        state=flow2_stream.state,
        schema=flow2_stream.schema,
        offers=[{"offer_id": 3717, "share": 100}],
        filters=flow2_stream.filters,
        payload={**(flow2_stream.payload or {}), "offers": [{"offer_id": 3717, "share": 100}]},
    )

    fetched = client.get(f"/api/campaigns/{campaign_id}?refresh=true", headers=auth_headers)
    reloaded = client.get(f"/api/campaigns/{campaign_id}?refresh=false", headers=auth_headers)

    assert fetched.status_code == 200
    offers = flow_by_name(reloaded.json(), "Flow 2")["offers"]
    removed_offer = next(offer for offer in offers if offer["offer_id"] == 3749)
    assert removed_offer["pending_action"] == "removed"
    assert removed_offer["weight"] == 0
    assert removed_offer["stats"] == {"redirects": 0}


def test_restore_removed_offer_pushes_it_back_to_keitaro(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )
    client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)
    client.post(f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3749/stage-remove", headers=auth_headers)
    client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)

    restored = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3749/restore",
        headers=auth_headers,
    )
    pushed = client.post(f"/api/campaigns/{campaign_id}/streams/push-to-kt", headers=auth_headers)
    reloaded = client.get(f"/api/campaigns/{campaign_id}?refresh=false", headers=auth_headers)

    assert restored.status_code == 200
    assert pushed.status_code == 200
    offers = flow_by_name(reloaded.json(), "Flow 2")["offers"]
    assert next(offer for offer in offers if offer["offer_id"] == 3749)["pending_action"] is None
    assert sorted(offer["offer_id"] for offer in offers if offer["pending_action"] is None) == [3717, 3749]


def test_pin_keeps_weight_when_other_offer_is_removed(
    client: TestClient,
    auth_headers: dict[str, str],
    create_payload: dict,
) -> None:
    created = client.post("/api/campaigns", json=create_payload, headers=auth_headers)
    created_body = created.json()
    campaign_id = created_body["id"]
    flow_id = flow_by_name(created_body, "Flow 2")["id"]
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]"},
        headers=auth_headers,
    )
    client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers",
        json={"offer_id": 4000, "name": "Pinned weight test offer"},
        headers=auth_headers,
    )

    pinned = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3749/toggle-pin",
        headers=auth_headers,
    )
    removed = client.post(
        f"/api/campaigns/{campaign_id}/streams/{flow_id}/offers/3717/stage-remove",
        headers=auth_headers,
    )

    assert pinned.status_code == 200
    assert next(offer for offer in pinned.json()["offers"] if offer["offer_id"] == 3749)["weight"] == 34
    offers = removed.json()["offers"]
    assert next(offer for offer in offers if offer["offer_id"] == 3749)["weight"] == 34
    assert next(offer for offer in offers if offer["offer_id"] == 4000)["weight"] == 66
