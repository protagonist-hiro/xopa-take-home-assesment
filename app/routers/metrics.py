import time
import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.api_keys import get_effective_limits
from app.database import get_db
from app.models import APIKeyConfig
from app.redis_client import get_redis


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metrics")
async def get_metrics(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()

    # ------------------------------------------------------------------
    # Total calls (lifetime counter)
    # ------------------------------------------------------------------
    total_calls = int(await redis.get("metrics:total_calls") or 0)
    pending_uploads = int(await redis.get("metrics:pending_uploads") or 0)
    # Guard against counter drift going negative
    if pending_uploads < 0:
        pending_uploads = 0

    # ------------------------------------------------------------------
    # Active calls: union of all per-key active-call sets
    # ------------------------------------------------------------------
    active_call_ids: set = set()
    active_keys = await redis.keys("active_calls:*")
    for key in active_keys:
        members = await redis.smembers(key)
        active_call_ids.update(members)
    active_count = len(active_call_ids)

    # ------------------------------------------------------------------
    # CPS per API key (count entries in the last 1-second window)
    # ------------------------------------------------------------------
    now = time.time()
    window_start = now - 1.0
    cps_data: dict[str, int] = {}
    cps_keys = await redis.keys("cps:*")
    for key in cps_keys:
        api_key_part = key[len("cps:"):]
        count = await redis.zcount(key, window_start, "+inf")
        cps_data[api_key_part] = int(count)

    completed_calls = max(total_calls - active_count, 0)

    stmt = select(APIKeyConfig.api_key).where(APIKeyConfig.is_active.is_(True))
    active_db_keys = (await db.execute(stmt)).scalars().all()
    limits_map: dict[str, dict[str, int]] = {}
    for key in active_db_keys:
        limits = await get_effective_limits(db, key)
        limits_map[key] = {
            "max_concurrent_calls": limits.max_concurrent_calls,
            "max_cps": limits.max_cps,
            "cps_window_seconds": limits.cps_window_seconds,
        }

    metrics_text = build_prometheus_metrics(
        total_calls=total_calls,
        active_calls=active_count,
        completed_calls=completed_calls,
        pending_uploads=pending_uploads,
        cps_current=cps_data,
        limits_map=limits_map,
    )
    return Response(content=metrics_text, media_type="text/plain; version=0.0.4")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_prometheus_metrics(
    total_calls: int,
    active_calls: int,
    completed_calls: int,
    pending_uploads: int,
    cps_current: dict[str, int],
    limits_map: dict[str, dict[str, int]],
) -> str:
    lines = [
        "# HELP comm_calls_total Total calls created.",
        "# TYPE comm_calls_total counter",
        f"comm_calls_total {total_calls}",
        "# HELP comm_calls_active Currently active calls.",
        "# TYPE comm_calls_active gauge",
        f"comm_calls_active {active_calls}",
        "# HELP comm_calls_completed_total Total calls completed.",
        "# TYPE comm_calls_completed_total counter",
        f"comm_calls_completed_total {completed_calls}",
        "# HELP comm_recording_uploads_pending Pending recording uploads.",
        "# TYPE comm_recording_uploads_pending gauge",
        f"comm_recording_uploads_pending {pending_uploads}",
        "# HELP comm_cps_current Current calls-per-second by API key.",
        "# TYPE comm_cps_current gauge",
    ]

    for key, value in sorted(cps_current.items()):
        label = _escape_label(key)
        lines.append(f'comm_cps_current{{api_key="{label}"}} {value}')

    lines.extend(
        [
            "# HELP comm_api_key_limit_max_concurrent Configured max concurrent calls by API key.",
            "# TYPE comm_api_key_limit_max_concurrent gauge",
            "# HELP comm_api_key_limit_max_cps Configured max CPS by API key.",
            "# TYPE comm_api_key_limit_max_cps gauge",
            "# HELP comm_api_key_limit_cps_window_seconds Configured CPS window seconds by API key.",
            "# TYPE comm_api_key_limit_cps_window_seconds gauge",
        ]
    )

    for key, limits in sorted(limits_map.items()):
        label = _escape_label(key)
        lines.append(
            f'comm_api_key_limit_max_concurrent{{api_key="{label}"}} {limits["max_concurrent_calls"]}'
        )
        lines.append(f'comm_api_key_limit_max_cps{{api_key="{label}"}} {limits["max_cps"]}')
        lines.append(
            f'comm_api_key_limit_cps_window_seconds{{api_key="{label}"}} {limits["cps_window_seconds"]}'
        )

    return "\n".join(lines) + "\n"
