from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api_keys import EffectiveLimits, ensure_default_api_keys, get_effective_limits


class _Settings:
    MAX_CONCURRENT_CALLS_PER_KEY = 5
    MAX_CPS_PER_KEY = 2
    CPS_WINDOW_SECONDS = 1


@pytest.mark.asyncio
async def test_get_effective_limits_returns_defaults_when_missing(monkeypatch):
    monkeypatch.setattr("app.api_keys.get_settings", lambda: _Settings())

    result_proxy = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result_proxy))

    limits = await get_effective_limits(db, "any-key")
    assert limits == EffectiveLimits(5, 2, 1)


@pytest.mark.asyncio
async def test_get_effective_limits_applies_row_overrides(monkeypatch):
    monkeypatch.setattr("app.api_keys.get_settings", lambda: _Settings())

    row = SimpleNamespace(max_concurrent_calls=10, max_cps=4, cps_window_seconds=3)
    result_proxy = SimpleNamespace(scalar_one_or_none=lambda: row)
    db = SimpleNamespace(execute=AsyncMock(return_value=result_proxy))

    limits = await get_effective_limits(db, "vip-key")
    assert limits == EffectiveLimits(10, 4, 3)


@pytest.mark.asyncio
async def test_ensure_default_api_keys_seeds_missing(monkeypatch):
    monkeypatch.setattr("app.api_keys.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.api_keys.get_valid_api_keys", lambda: ["test-key-1", "test-key-2"])

    scalars_proxy = SimpleNamespace(all=lambda: ["test-key-1"])
    result_proxy = SimpleNamespace(scalars=lambda: scalars_proxy)

    added = []
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result_proxy),
        add=lambda row: added.append(row),
        commit=AsyncMock(),
    )

    await ensure_default_api_keys(db)

    assert len(added) == 1
    assert added[0].api_key == "test-key-2"
    db.commit.assert_awaited_once()
