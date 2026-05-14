import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires live DB — run with docker compose")
async def test_detections_icebergs_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/detections/icebergs")
    assert resp.status_code == 200
