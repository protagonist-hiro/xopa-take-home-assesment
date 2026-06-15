from sqlalchemy import Column, String, JSON, DateTime, Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase
import uuid
from datetime import datetime, timezone


class Base(DeclarativeBase):
    pass


class Call(Base):
    __tablename__ = "calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_number = Column(String(50), nullable=False)
    to_number = Column(String(50), nullable=False)
    api_key = Column(String(200), nullable=False, index=True)
    status = Column(String(20), default="queued", nullable=False)
    call_metadata = Column("metadata", JSON, default=dict)
    recording_url = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    state_history = Column(JSON, default=list)


class APIKeyConfig(Base):
    __tablename__ = "api_key_configs"

    api_key = Column(String(200), primary_key=True)
    is_active = Column(Boolean, nullable=False, default=True)
    max_concurrent_calls = Column(Integer, nullable=True)
    max_cps = Column(Integer, nullable=True)
    cps_window_seconds = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
