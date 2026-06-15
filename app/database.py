from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import get_settings
from app.models import Base

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed configured test API keys into DB if missing.
    from app.api_keys import ensure_default_api_keys

    async with AsyncSessionLocal() as session:
        await ensure_default_api_keys(session)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
