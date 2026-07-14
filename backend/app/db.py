"""Async database engine, session, and idempotent schema initialization."""

import asyncio
import logging
from collections.abc import AsyncIterator

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "relational_db"
    postgres_port: int = 5432
    embedding_dim: int = 384
    db_init_max_attempts: int = 10
    db_init_retry_seconds: float = 2.0

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()

engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session."""
    async with async_session_factory() as session:
        yield session


SCHEMA_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS pdf_documents (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        filename TEXT NOT NULL,
        content_hash TEXT UNIQUE NOT NULL,          -- dedupe re-uploads
        page_count INT,
        status TEXT NOT NULL DEFAULT 'processing',  -- processing|ready|failed
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        document_id UUID NOT NULL REFERENCES pdf_documents(id) ON DELETE CASCADE,
        chunk_index INT NOT NULL,
        page_number INT,
        content TEXT NOT NULL,
        embedding vector({embedding_dim}),
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks
        USING hnsw (embedding vector_cosine_ops)
    """,
    "CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks (document_id)",
]


async def init_db() -> None:
    """Create the pgvector extension, tables, and indexes if they don't already exist.

    Retries with a fixed delay since the database container may still be
    starting up when this runs (no depends_on/healthcheck in docker-compose).
    """
    statements = [s.format(embedding_dim=settings.embedding_dim) for s in SCHEMA_STATEMENTS]

    for attempt in range(1, settings.db_init_max_attempts + 1):
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(text(statement))
            logger.info("Database schema initialized")
            return
        except OperationalError:
            if attempt == settings.db_init_max_attempts:
                logger.error("Database not reachable after %d attempts", attempt)
                raise
            logger.warning(
                "Database not ready (attempt %d/%d), retrying in %.1fs",
                attempt,
                settings.db_init_max_attempts,
                settings.db_init_retry_seconds,
            )
            await asyncio.sleep(settings.db_init_retry_seconds)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await init_db()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
