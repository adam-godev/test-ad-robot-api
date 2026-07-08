import re

import pytest

from app.core.config import Settings
from app.integrations.keitaro.client import KeitaroClient, KeitaroError
from app.services.campaigns import CampaignService
from app.services.aliases import generate_alias
from app.services.geo import normalize_geo_codes
from app.services.weights import distribute_weights


def test_geo_normalization_deduplicates_and_preserves_order() -> None:
    assert normalize_geo_codes("mx, AU, ro, au") == ["MX", "AU", "RO"]


def test_geo_normalization_rejects_empty_geo() -> None:
    with pytest.raises(ValueError, match="At least one GEO"):
        normalize_geo_codes([" ", ""])


def test_geo_normalization_rejects_invalid_geo() -> None:
    with pytest.raises(ValueError, match="Invalid GEO"):
        normalize_geo_codes(["AU", "XX"])


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),
        (4, [25, 25, 25, 25]),
    ],
)
def test_distribute_weights(count: int, expected: list[int]) -> None:
    assert distribute_weights(count) == expected
    assert sum(distribute_weights(count)) == 100


def test_generate_alias_when_alias_is_not_passed() -> None:
    alias = generate_alias()
    assert re.fullmatch(r"[A-Za-z0-9]{6}", alias)


def test_settings_normalizes_keitaro_base_url() -> None:
    settings = Settings(KEITARO_BASE_URL="https://demo.keitaro.io/")

    assert settings.keitaro_base_url == "https://demo.keitaro.io"


def test_report_metrics_are_extracted_from_nested_keitaro_payload() -> None:
    report = {
        "data": {
            "rows": [
                {
                    "campaign_id": 101,
                    "metrics": {
                        "clicks": "1,234",
                        "unique clicks": "900",
                        "bots": 12,
                        "conversions": 8,
                        "revenue": "$45.50",
                        "cost": "10.25",
                        "profit": "35.25",
                        "CR": "0.65%",
                    },
                }
            ]
        }
    }

    metrics = CampaignService._metrics_from_report(report)
    stats = CampaignService._stats_response_from_metrics(metrics)

    assert stats == {
        "clicks": 1234,
        "unique_clicks": 900,
        "bots": 12,
        "conversions": 8,
        "revenue": 45.5,
        "cost": 10.25,
        "profit": 35.25,
        "cr": 0.65,
    }


def test_report_metrics_select_matching_campaign_row() -> None:
    report = {
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

    metrics = CampaignService._metrics_from_report(report, campaign_name="Google Ads Fitness App Split")
    stats = CampaignService._stats_response_from_metrics(metrics)

    assert stats["clicks"] == 15134
    assert stats["conversions"] == 2276
    assert stats["revenue"] == 1151.92
    assert stats["cost"] == 142.69
    assert stats["profit"] == 1009.23
    assert round(stats["cr"], 2) == 15.04


def test_keitaro_offer_search_handles_list_fields() -> None:
    class SearchClient(KeitaroClient):
        def __init__(self) -> None:
            pass

        def _request(self, method: str, path: str, **kwargs):
            return [
                {
                    "id": 123,
                    "name": "Offer 123",
                    "country": ["RO", "PL"],
                    "state": ["active"],
                    "affiliate_network": ["Miaflow"],
                }
            ]

    offers = SearchClient().search_offers("pl", 20)

    assert len(offers) == 1
    assert offers[0].country == "RO, PL"
    assert offers[0].state == "active"
    assert offers[0].affiliate_network == "Miaflow"

def test_keitaro_validation_error_names_env_fields() -> None:
    error = KeitaroError(
        "Keitaro rejected payload",
        http_status=422,
        details={"group_id": ["does not exist"]},
    )

    app_error = CampaignService._keitaro_to_app_error(error)

    assert app_error.code == "KEITARO_VALIDATION_ERROR"
    assert app_error.message == "Keitaro rejected environment configuration. Check KEITARO_GROUP_ID in .env."
