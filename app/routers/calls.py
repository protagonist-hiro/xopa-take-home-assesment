import asyncio
import json
import logging
import uuid

from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_api_key
from app.api_keys import get_effective_limits
from app.call_machine import start_call_machine
from app.config import get_settings
from app.database import get_db
from app.models import Call
from app.rate_limit import check_and_add_concurrent, check_and_increment_cps
from app.redis_client import get_redis
from app.schemas import CallCreate, CallResponse
from app.ws_manager import manager as ws_manager

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /calls — initiate a new call
# ---------------------------------------------------------------------------
@router.post("/calls", response_model=CallResponse, status_code=201)
async def initiate_call(
    body: CallCreate,
    request: Request,
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    limits = await get_effective_limits(db, api_key)

    # CPS check (sliding window, atomic Lua script)
    if not await check_and_increment_cps(
        redis,
        api_key,
        limits.max_cps,
        limits.cps_window_seconds,
    ):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded"},
        )

    # Concurrent-call check (atomic Lua script)
    call_id = str(uuid.uuid4())
    if not await check_and_add_concurrent(
        redis,
        api_key,
        call_id,
        limits.max_concurrent_calls,
    ):
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded"},
        )

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    host = request.headers.get("host", f"localhost:{settings.SERVICE_PORT}")
    public_base_url = f"{request.url.scheme}://{host}"

    # ── Redis: live state ──────────────────────────────────────────────────
    # Redis 3.x does not support multi-field HSET; write fields individually.
    call_key = f"call:{call_id}"
    await redis.hset(call_key, "id", call_id)
    await redis.hset(call_key, "from", body.from_number)
    await redis.hset(call_key, "to", body.to_number)
    await redis.hset(call_key, "api_key", api_key)
    await redis.hset(call_key, "status", "queued")
    await redis.hset(call_key, "created_at", now_iso)
    await redis.hset(call_key, "updated_at", now_iso)
    await redis.hset(call_key, "public_base_url", public_base_url)
    await redis.hset(call_key, "recording_url", "")
    await redis.expire(call_key, 86400)

    # ── PostgreSQL: persistent record ──────────────────────────────────────
    call = Call(
        id=uuid.UUID(call_id),
        from_number=body.from_number,
        to_number=body.to_number,
        api_key=api_key,
        status="queued",
        call_metadata=body.metadata or {},
        created_at=now,
        updated_at=now,
        state_history=[],
    )
    db.add(call)
    await db.commit()

    # ── Metrics counter ────────────────────────────────────────────────────
    await redis.incr("metrics:total_calls")

    # ── Build WebSocket URL ────────────────────────────────────────────────
    ws_url = f"ws://{host}/ws/{call_id}"

    # ── Kick off the async state machine ──────────────────────────────────
    start_call_machine(call_id, api_key)

    return CallResponse(
        call_id=call_id,
        status="queued",
        from_number=body.from_number,
        to_number=body.to_number,
        websocket_url=ws_url,
        created_at=now_iso,
    )


# ---------------------------------------------------------------------------
# GET /calls/{call_id} — retrieve current call state
# ---------------------------------------------------------------------------
@router.get("/calls/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: str,
    api_key: str = Depends(verify_api_key),
):
    redis = await get_redis()

    data = await redis.hgetall(f"call:{call_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Call not found")

    history_raw = await redis.lrange(f"call:{call_id}:history", 0, -1)
    history = [json.loads(h) for h in history_raw]

    host = f"localhost:{settings.SERVICE_PORT}"
    return CallResponse(
        call_id=call_id,
        status=data.get("status", "unknown"),
        from_number=data.get("from", ""),
        to_number=data.get("to", ""),
        websocket_url=f"ws://{host}/ws/{call_id}",
        created_at=data.get("created_at", ""),
        recording_url=data.get("recording_url") or None,
        state_history=history,
    )


# ---------------------------------------------------------------------------
# WebSocket /ws/{call_id} — real-time call events
# ---------------------------------------------------------------------------
@router.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await ws_manager.connect(call_id, websocket)
    try:
        # Immediately push the current state to the new subscriber
        redis = await get_redis()
        data = await redis.hgetall(f"call:{call_id}")
        if data:
            await websocket.send_json(
                {
                    "event": "current_state",
                    "call_id": call_id,
                    "status": data.get("status", "unknown"),
                    "timestamp": data.get("updated_at", ""),
                }
            )

        # Hold the connection open; send periodic pings so proxies don't drop it
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"event": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error for call %s: %s", call_id, exc)
    finally:
        await ws_manager.disconnect(call_id, websocket)
