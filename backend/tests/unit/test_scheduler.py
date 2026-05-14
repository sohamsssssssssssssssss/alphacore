from data.scheduler import DataScheduler


class DummyFetcher:
    symbols = []


class DummyState:
    async def update(self, *_args, **_kwargs):
        return None


def test_scheduler_constructs():
    scheduler = DataScheduler(DummyFetcher(), DummyState())
    assert scheduler is not None
