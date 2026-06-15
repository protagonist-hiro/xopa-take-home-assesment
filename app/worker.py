"""
ARQ background worker.

Handles async recording uploads after a call completes.
Run with:  python -m arq app.worker.WorkerSettings
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
import inspect
import io
import math
import struct
import wave
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

def _build_mock_tone_wav(
    seconds: float = 1.2,
    freq_hz: float = 440.0,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a short audible sine-wave tone for debug playback."""
    frame_count = max(1, int(seconds * sample_rate))
    amplitude = 11000
    raw = bytearray()
    for i in range(frame_count):
        t = i / sample_rate
        sample = int(amplitude * math.sin(2 * math.pi * freq_hz * t))
        raw.extend(struct.pack("<h", sample))

    buff = io.BytesIO()
    with wave.open(buff, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit PCM
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(raw))
    return buff.getvalue()


_MOCK_AUDIO: bytes = _build_mock_tone_wav()


async def _resolve_public_base_url(call_id: str) -> str:
    """Read per-call base URL written at call creation; fallback to settings."""
    import redis.asyncio as aioredis

    r = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        base = await r.hget(f"call:{call_id}", "public_base_url")
        return (base or "").strip() or settings.PUBLIC_BASE_URL
    finally:
        close_fn = getattr(r, "aclose", None) or getattr(r, "close", None)
        if close_fn is not None:
            maybe_awaitable = close_fn()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable


async def upload_recording(ctx: dict, call_id: str) -> dict:
    """
    ARQ job: upload a mock WAV to MinIO/S3 then update the call record
    in both PostgreSQL and Redis.
    """
    logger.info("Recording upload started for call %s", call_id)

    recording_url: str | None = None

    # ------------------------------------------------------------------
    # 1. Persist recording bytes
    # ------------------------------------------------------------------
    try:
        backend = settings.STORAGE_BACKEND.lower().strip()
        if backend == "local":
            local_dir = Path(settings.LOCAL_RECORDINGS_DIR)
            local_dir.mkdir(parents=True, exist_ok=True)
            out_file = local_dir / f"{call_id}.wav"
            out_file.write_bytes(_MOCK_AUDIO)
            public_base_url = await _resolve_public_base_url(call_id)
            recording_url = f"{public_base_url}/recordings/{call_id}.wav"
            logger.info("Stored local recording for call %s → %s", call_id, out_file)
        else:
            import boto3
            from botocore.exceptions import ClientError

            s3 = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
            )
            key = f"recordings/{call_id}.wav"
            s3.put_object(
                Bucket=settings.S3_BUCKET,
                Key=key,
                Body=_MOCK_AUDIO,
                ContentType="audio/wav",
            )
            recording_url = f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET}/{key}"
            logger.info("Uploaded recording for call %s → %s", call_id, recording_url)
    except Exception as exc:
        logger.error("Recording persistence failed for call %s: %s", call_id, exc)

    # ------------------------------------------------------------------
    # 2. Persist recording URL to PostgreSQL
    # ------------------------------------------------------------------
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import update as sa_update
        from app.models import Call

        engine = create_async_engine(settings.DATABASE_URL)
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            await session.execute(
                sa_update(Call)
                .where(Call.id == _uuid.UUID(call_id))
                .values(
                    recording_url=recording_url,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        await engine.dispose()
        logger.info("DB updated for call %s", call_id)
    except Exception as exc:
        logger.error("DB update failed for call %s: %s", call_id, exc)

    # ------------------------------------------------------------------
    # 3. Update Redis: store URL, decrement pending counter
    # ------------------------------------------------------------------
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
        pipe = r.pipeline()
        pipe.hset(f"call:{call_id}", "recording_url", recording_url or "")
        pipe.decr("metrics:pending_uploads")
        await pipe.execute()
        close_fn = getattr(r, "aclose", None) or getattr(r, "close", None)
        if close_fn is not None:
            maybe_awaitable = close_fn()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
    except Exception as exc:
        logger.error("Redis update failed for call %s: %s", call_id, exc)

    return {"call_id": call_id, "recording_url": recording_url}


# ---------------------------------------------------------------------------
# ARQ worker settings
# ---------------------------------------------------------------------------
from arq.connections import RedisSettings  # noqa: E402


class WorkerSettings:
    functions = [upload_recording]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 10
    job_timeout = 60
    keep_result = 300  # seconds to retain job results
