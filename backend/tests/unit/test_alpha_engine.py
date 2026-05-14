import pytest

from engines.alpha_engine import AlphaEngine


@pytest.mark.asyncio
async def test_alpha_engine_no_snapshot_returns_none(monkeypatch):
    class FakeDB:
        async def fetch_one(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr("engines.alpha_engine.get_database", lambda: FakeDB())
    engine = AlphaEngine()
    assert await engine.generate_signal("RELIANCE") is None
