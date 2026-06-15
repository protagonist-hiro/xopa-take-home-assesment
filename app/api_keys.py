from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, get_valid_api_keys
from app.models import APIKeyConfig


@dataclass(frozen=True)
class EffectiveLimits:
    max_concurrent_calls: int
    max_cps: int
    cps_window_seconds: int


async def ensure_default_api_keys(db: AsyncSession) -> None:
    """Seed DB with configured test keys if they are missing."""
    keys = [k for k in get_valid_api_keys() if k]
    if not keys:
        return

    stmt = select(APIKeyConfig.api_key).where(APIKeyConfig.api_key.in_(keys))
    existing = set((await db.execute(stmt)).scalars().all())

    settings = get_settings()
    now = datetime.now(timezone.utc)
    missing = [k for k in keys if k not in existing]
    for key in missing:
        db.add(
            APIKeyConfig(
                api_key=key,
                is_active=True,
                max_concurrent_calls=settings.MAX_CONCURRENT_CALLS_PER_KEY,
                max_cps=settings.MAX_CPS_PER_KEY,
                cps_window_seconds=settings.CPS_WINDOW_SECONDS,
                created_at=now,
                updated_at=now,
            )
        )

    if missing:
        await db.commit()


async def is_api_key_allowed(db: AsyncSession, api_key: str) -> bool:
    stmt = select(APIKeyConfig.api_key).where(
        APIKeyConfig.api_key == api_key,
        APIKeyConfig.is_active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def get_effective_limits(db: AsyncSession, api_key: str) -> EffectiveLimits:
    settings = get_settings()
    defaults = EffectiveLimits(
        max_concurrent_calls=settings.MAX_CONCURRENT_CALLS_PER_KEY,
        max_cps=settings.MAX_CPS_PER_KEY,
        cps_window_seconds=settings.CPS_WINDOW_SECONDS,
    )

    stmt = select(APIKeyConfig).where(
        APIKeyConfig.api_key == api_key,
        APIKeyConfig.is_active.is_(True),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return defaults

    return EffectiveLimits(
        max_concurrent_calls=row.max_concurrent_calls or defaults.max_concurrent_calls,
        max_cps=row.max_cps or defaults.max_cps,
        cps_window_seconds=row.cps_window_seconds or defaults.cps_window_seconds,
    )
