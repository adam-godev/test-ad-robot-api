import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.api.dependencies import get_keitaro_client
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.integrations.keitaro.client import (
    KeitaroCampaign,
    KeitaroError,
    KeitaroOffer,
    KeitaroStream,
)
from app.main import app


class FakeKeitaroClient:
    def __init__(self) -> None:
        self.offers = {
            3749: KeitaroOffer(
                id=3749,
                name="Miaflow [BEAUTY-RO-BE_0009] [pl - spin ro-]",
                country="RO",
                state="active",
                affiliate_network="Miaflow",
                url="https://offer-3749.test",
            ),
            3717: KeitaroOffer(
                id=3717,
                name="Miaflow [BEAUTY-RO-BE_0008] [pl - prize ro-]",
                country="RO",
                state="active",
                affiliate_network="Miaflow",
                url="https://offer-3717.test",
            ),
        }
        self.campaigns: dict[int, KeitaroCampaign] = {}
        self.campaign_payloads: list[dict] = []
        self.stream_payloads: list[dict] = []
        self.updated_streams: list[tuple[int, dict]] = []
        self.archived_campaigns: list[int] = []
        self.streams: list[KeitaroStream] = []
        self.campaign_stream_requests: list[int] = []
        self.report_payload: dict = {}
        self.report_requests: list[dict] = []
        self.raise_on_create_campaign: KeitaroError | None = None
        self.raise_on_stream_number: tuple[int, KeitaroError] | None = None

    def get_offer(self, offer_id: int) -> KeitaroOffer:
        if offer_id not in self.offers:
            raise KeitaroError("Offer not found", http_status=404)
        return self.offers[offer_id]

    def search_offers(self, query: str, limit: int) -> list[KeitaroOffer]:
        query = query.lower()
        return [offer for offer in self.offers.values() if query in offer.name.lower()][:limit]

    def create_campaign(self, payload: dict) -> KeitaroCampaign:
        if self.raise_on_create_campaign:
            raise self.raise_on_create_campaign
        self.campaign_payloads.append(payload)
        campaign = KeitaroCampaign(id=101, name=payload["name"], alias=payload["alias"], state="active", payload=payload)
        self.campaigns[campaign.id] = campaign
        return campaign

    def archive_campaign(self, campaign_id: int) -> None:
        self.archived_campaigns.append(campaign_id)

    def create_stream(self, payload: dict) -> KeitaroStream:
        next_number = len(self.stream_payloads) + 1
        if self.raise_on_stream_number and self.raise_on_stream_number[0] == next_number:
            raise self.raise_on_stream_number[1]
        stream = KeitaroStream(
            id=200 + next_number,
            name=payload["name"],
            position=payload.get("position"),
            state=payload.get("state"),
            schema=payload.get("schema"),
            offers=list(payload.get("offers") or []),
            filters=list(payload.get("filters") or []),
            payload=dict(payload),
        )
        self.stream_payloads.append(payload)
        self.streams.append(stream)
        return stream

    def list_campaigns(self) -> list[KeitaroCampaign]:
        return list(self.campaigns.values())

    def get_campaign(self, campaign_id: int) -> KeitaroCampaign:
        if campaign_id not in self.campaigns:
            raise KeitaroError("Campaign not found", http_status=404)
        return self.campaigns[campaign_id]

    def get_campaign_streams(self, campaign_id: int) -> list[KeitaroStream]:
        self.campaign_stream_requests.append(campaign_id)
        return list(self.streams)

    def update_stream(self, stream_id: int, payload: dict) -> KeitaroStream:
        self.updated_streams.append((stream_id, payload))
        stream = KeitaroStream(
            id=stream_id,
            name=payload.get("name"),
            position=payload.get("position"),
            state=payload.get("state"),
            schema=payload.get("schema"),
            offers=list(payload.get("offers") or []),
            filters=list(payload.get("filters") or []),
            payload=dict(payload),
        )
        self.streams = [stream if existing.id == stream_id else existing for existing in self.streams]
        return stream

    def get_report(self, payload: dict) -> dict:
        self.report_requests.append(payload)
        return self.report_payload


@pytest.fixture
def fake_keitaro() -> FakeKeitaroClient:
    return FakeKeitaroClient()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'test.db'}",
        KEITARO_BASE_URL="https://keitaro.test",
        KEITARO_API_KEY="secret-test-key",
        KEITARO_CAMPAIGN_DOMAIN_URL="https://tracker.test",
        KEITARO_DOMAIN_ID=11,
        KEITARO_GROUP_ID=22,
        KEITARO_TRAFFIC_SOURCE_ID=33,
    )


@pytest.fixture
def client(settings: Settings, fake_keitaro: FakeKeitaroClient):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_keitaro_client] = lambda: fake_keitaro

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {}


@pytest.fixture
def create_payload() -> dict:
    return {"name": "campaign 2", "geo_codes": ["AU"], "offer_id": 3749, "alias": "wVqN1R"}
