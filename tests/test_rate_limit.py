from types import SimpleNamespace

import pytest

from app.rate_limit import check_and_add_concurrent, check_and_increment_cps


class FakeRedis:
    def __init__(self, result=1):
        self.result = result
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.result


@pytest.mark.asyncio
async def test_check_and_increment_cps_uses_passed_limits():
    redis = FakeRedis(result=1)

    ok = await check_and_increment_cps(
        redis=redis,
        api_key="test-key-1",
        max_cps=7,
        cps_window_seconds=3,
    )

    assert ok is True
    assert len(redis.calls) == 1
    _, _, key, window_start, now, limit, _ = redis.calls[0]
    assert key == "cps:test-key-1"
    assert float(now) >= float(window_start)
    assert limit == "7"


@pytest.mark.asyncio
async def test_check_and_add_concurrent_uses_passed_limit():
    redis = FakeRedis(result=0)

    ok = await check_and_add_concurrent(
        redis=redis,
        api_key="test-key-1",
        call_id="cid-123",
        max_concurrent_calls=11,
    )

    assert ok is False
    assert len(redis.calls) == 1
    _, _, key, call_id, limit = redis.calls[0]
    assert key == "active_calls:test-key-1"
    assert call_id == "cid-123"
    assert limit == "11"
