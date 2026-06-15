"""
Call state machine.

Each call is driven by an asyncio.Task that sleeps between state
transitions, updates Redis, and broadcasts via the WebSocket manager.
When the call reaches COMPLETED the task enqueues an ARQ recording-
upload job and persists the final state to PostgreSQL.
"""

import asyncio
import inspect
import json
import logging
import random
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import get_settings
from app.ws_manager import manager as ws_manager
from app.rate_limit import remove_active_call

logger = logging.getLogger(__name__)
settings = get_settings()

# Keep strong references so tasks aren't garbage-collected
_running_tasks: set = set()

# ---------------------------------------------------------------------------
# State-machine paths: list of (from_state, to_state, min_s, max_s)
# ---------------------------------------------------------------------------
_PATHS = [
    # Path A: answered → completed
    [
        ("queued", "ringing", 0.5, 2.0),
        ("ringing", "answered", 2.0, 5.0),
        ("answered", "completed", 5.0, 15.0),
    ],
    # Path B: unanswered → completed
    [
        ("queued", "ringing", 0.5, 2.0),
        ("ringing", "unanswered", 2.0, 5.0),
        ("unanswered", "completed", 1.0, 3.0),
    ],
]


async def _close_client(client) -> None:
    close_fn = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close_fn is None:
        return
    maybe_awaitable = close_fn()
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


async def _transition(
    redis: aioredis.Redis,
    call_id: str,
    from_state: str,
    to_state: str,
) -> None:
    """Apply one state transition: update Redis + broadcast WebSocket event."""
    now = datetime.now(timezone.utc).isoformat()

    call_key = f"call:{call_id}"
    pipe = redis.pipeline()
    # Redis 3.x compatibility: one field per HSET command.
    pipe.hset(call_key, "status", to_state)
    pipe.hset(call_key, "updated_at", now)
    if to_state == "completed":
        pipe.hset(call_key, "completed_at", now)

    history_entry = json.dumps({"from": from_state, "to": to_state, "timestamp": now})
    pipe.rpush(f"call:{call_id}:history", history_entry)
    pipe.expire(f"call:{call_id}:history", 86400)
    await pipe.execute()

    await ws_manager.broadcast(
        call_id,
        {
            "event": "state_change",
            "call_id": call_id,
            "from_state": from_state,
            "to_state": to_state,
            "timestamp": now,
        },
    )
    logger.info("Call %s: %s → %s", call_id, from_state, to_state)


async def _persist_completed(call_id: str, redis: aioredis.Redis) -> None:
    """Write the final state + history back to PostgreSQL."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import update as sa_update
        from app.models import Call
        import uuid as _uuid

        history_raw = await redis.lrange(f"call:{call_id}:history", 0, -1)
        history = [json.loads(h) for h in history_raw]
        completed_at_raw = await redis.hget(f"call:{call_id}", "completed_at")
        completed_at = datetime.fromisoformat(completed_at_raw) if completed_at_raw else datetime.now(timezone.utc)

        eng = create_async_engine(settings.DATABASE_URL)
        Session = sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            await session.execute(
                sa_update(Call)
                .where(Call.id == _uuid.UUID(call_id))
                .values(
                    status="completed",
                    state_history=history,
                    completed_at=completed_at,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        await eng.dispose()
    except Exception as exc:
        logger.error("Failed to persist completed call %s: %s", call_id, exc)


async def _enqueue_upload(call_id: str) -> None:
    """Enqueue an ARQ recording-upload job and bump the pending counter."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        pool = await create_pool(redis_settings)

        r = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
        await r.incr("metrics:pending_uploads")
        await _close_client(r)

        await pool.enqueue_job("upload_recording", call_id)
        await _close_client(pool)
        logger.info("Enqueued recording upload for call %s", call_id)
    except Exception as exc:
        logger.error("Failed to enqueue upload for call %s: %s", call_id, exc)


async def _run_machine(call_id: str, api_key: str) -> None:
    """Drive the call through its randomly-chosen path."""
    r = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        path = random.choice(_PATHS)
        for from_state, to_state, min_s, max_s in path:
            await asyncio.sleep(random.uniform(min_s, max_s))
            await _transition(r, call_id, from_state, to_state)

        # Call finished – housekeeping
        await remove_active_call(r, api_key, call_id)
        await _persist_completed(call_id, r)
        await _enqueue_upload(call_id)

    except asyncio.CancelledError:
        logger.info("Call machine cancelled: %s", call_id)
    except Exception as exc:
        logger.error("Call machine error for %s: %s", call_id, exc, exc_info=True)
    finally:
        await _close_client(r)


def start_call_machine(call_id: str, api_key: str) -> asyncio.Task:
    """Start the call state machine as a tracked background task."""
    task = asyncio.create_task(_run_machine(call_id, api_key))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return task
