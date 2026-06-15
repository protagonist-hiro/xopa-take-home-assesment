import time
import uuid

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Lua script: atomic sliding-window CPS check + increment
# Returns 1 if the request is allowed, 0 if rate-limited.
# ---------------------------------------------------------------------------
_LUA_CPS = """
local key          = KEYS[1]
local window_start = tonumber(ARGV[1])
local now          = tonumber(ARGV[2])
local limit        = tonumber(ARGV[3])
local member       = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, 2)
    return 1
else
    return 0
end
"""

# ---------------------------------------------------------------------------
# Lua script: atomic concurrent-call check + add
# Returns 1 if the call was added (under limit), 0 otherwise.
# ---------------------------------------------------------------------------
_LUA_CONCURRENT = """
local key     = KEYS[1]
local call_id = ARGV[1]
local limit   = tonumber(ARGV[2])

local count = redis.call('SCARD', key)
if count < limit then
    redis.call('SADD', key, call_id)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    return 0
end
"""


async def check_and_increment_cps(
    redis: aioredis.Redis,
    api_key: str,
    max_cps: int,
    cps_window_seconds: int,
) -> bool:
    """Sliding-window CPS check. Returns True if the request is allowed."""
    now = time.time()
    window_start = now - cps_window_seconds
    key = f"cps:{api_key}"
    member = str(uuid.uuid4())

    result = await redis.eval(
        _LUA_CPS,
        1,
        key,
        str(window_start),
        str(now),
        str(max_cps),
        member,
    )
    return bool(result)


async def check_and_add_concurrent(
    redis: aioredis.Redis,
    api_key: str,
    call_id: str,
    max_concurrent_calls: int,
) -> bool:
    """
    Atomically check concurrent-call limit and register the call.
    Returns True if the call was accepted (under limit).
    """
    key = f"active_calls:{api_key}"
    result = await redis.eval(
        _LUA_CONCURRENT,
        1,
        key,
        call_id,
        str(max_concurrent_calls),
    )
    return bool(result)


async def remove_active_call(
    redis: aioredis.Redis, api_key: str, call_id: str
) -> None:
    key = f"active_calls:{api_key}"
    await redis.srem(key, call_id)


async def get_concurrent_call_count(
    redis: aioredis.Redis, api_key: str
) -> int:
    count = await redis.scard(f"active_calls:{api_key}")
    return int(count or 0)
