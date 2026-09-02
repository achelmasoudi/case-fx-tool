from datetime import date, timedelta
import httpx
import pytest
import respx

from app.fx import _CACHE
from app.main import app
import app.main as main_mod

UPSTREAM_BASE = "http://127.0.0.1:54321"


@pytest.fixture(autouse=True)
def setup_env_and_cache(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", UPSTREAM_BASE)
    _CACHE.clear()
    yield
    _CACHE.clear()


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    if main_mod.http_client and not main_mod.http_client.is_closed:
        await main_mod.http_client.aclose()
        main_mod.http_client = None


@pytest.mark.asyncio
async def test_standard_conversion(client):
    with respx.mock(base_url=UPSTREAM_BASE) as respx_mock:
        route = respx_mock.get("/v1/2026-08-28").respond(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-08-28",
                "rates": {"TRY": 37.8912},
            },
        )
        response = await client.get(
            "/tools/convert",
            params={
                "amount": 100.0,
                "from": "EUR",
                "to": "TRY",
                "date": "2026-08-28",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["amount"] == 100.0
        assert data["from"] == "EUR"
        assert data["to"] == "TRY"
        assert data["rate"] == 37.8912
        assert data["result"] == 3789.12
        assert data["rate_date"] == "2026-08-28"
        assert data["asked_date"] == "2026-08-28"
        assert data["source"] == "ECB via frankfurter.dev"
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_weekend_date(client):
    with respx.mock(base_url=UPSTREAM_BASE) as respx_mock:
        route = respx_mock.get("/v1/2026-08-29").respond(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-08-28",
                "rates": {"USD": 1.085},
            },
        )
        response = await client.get(
            "/tools/convert",
            params={
                "amount": 100.0,
                "from": "EUR",
                "to": "USD",
                "date": "2026-08-29",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["asked_date"] == "2026-08-29"
        assert data["rate_date"] == "2026-08-28"
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_in_memory_cache(client):
    with respx.mock(base_url=UPSTREAM_BASE) as respx_mock:
        route = respx_mock.get("/v1/2026-08-28").respond(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-08-28",
                "rates": {"USD": 1.085},
            },
        )
        # Call 1
        resp1 = await client.get(
            "/tools/convert",
            params={
                "amount": 10.0,
                "from": "EUR",
                "to": "USD",
                "date": "2026-08-28",
            },
        )
        assert resp1.status_code == 200

        # Call 2
        resp2 = await client.get(
            "/tools/convert",
            params={
                "amount": 25.0,
                "from": "EUR",
                "to": "USD",
                "date": "2026-08-28",
            },
        )
        assert resp2.status_code == 200
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_same_currency(client):
    with respx.mock(base_url=UPSTREAM_BASE, assert_all_called=False) as respx_mock:
        route = respx_mock.get("/v1/2026-08-28").respond(200)
        response = await client.get(
            "/tools/convert",
            params={
                "amount": 50.0,
                "from": "EUR",
                "to": "EUR",
                "date": "2026-08-28",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["rate"] == 1.0
        assert data["result"] == 50.0
        assert data["from"] == "EUR"
        assert data["to"] == "EUR"
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_invalid_amounts(client):
    # Test amount = 0
    resp_zero = await client.get(
        "/tools/convert",
        params={
            "amount": 0,
            "from": "EUR",
            "to": "USD",
            "date": "2026-08-28",
        },
    )
    assert resp_zero.status_code == 400
    assert resp_zero.json()["error"] == "invalid_amount"

    # Test amount = -10
    resp_negative = await client.get(
        "/tools/convert",
        params={
            "amount": -10,
            "from": "EUR",
            "to": "USD",
            "date": "2026-08-28",
        },
    )
    assert resp_negative.status_code == 400
    assert resp_negative.json()["error"] == "invalid_amount"


@pytest.mark.asyncio
async def test_future_date(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = await client.get(
        "/tools/convert",
        params={
            "amount": 100,
            "from": "EUR",
            "to": "USD",
            "date": tomorrow,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "future_date"


@pytest.mark.asyncio
async def test_date_before_series(client):
    response = await client.get(
        "/tools/convert",
        params={
            "amount": 100,
            "from": "EUR",
            "to": "USD",
            "date": "1998-12-31",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "date_before_series"


@pytest.mark.asyncio
async def test_upstream_errors(client):
    with respx.mock(base_url=UPSTREAM_BASE) as respx_mock:
        # Simulate timeout -> 504
        respx_mock.get("/v1/2026-08-28").mock(
            side_effect=httpx.ReadTimeout("Timeout from upstream")
        )
        resp_timeout = await client.get(
            "/tools/convert",
            params={
                "amount": 100,
                "from": "EUR",
                "to": "USD",
                "date": "2026-08-28",
            },
        )
        assert resp_timeout.status_code == 504
        assert resp_timeout.json()["error"] == "upstream_timeout"

    _CACHE.clear()

    with respx.mock(base_url=UPSTREAM_BASE) as respx_mock:
        # Simulate 500 error -> 502
        respx_mock.get("/v1/2026-08-28").respond(500, text="Internal Server Error")
        resp_500 = await client.get(
            "/tools/convert",
            params={
                "amount": 100,
                "from": "EUR",
                "to": "USD",
                "date": "2026-08-28",
            },
        )
        assert resp_500.status_code == 502
        assert resp_500.json()["error"] == "upstream_error"
