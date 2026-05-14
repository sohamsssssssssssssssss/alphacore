import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires live DB — run with docker compose")
async def test_orderbook_api_symbol_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/orderbook/RELIANCE")
    assert resp.status_code in {200, 404, 503}
