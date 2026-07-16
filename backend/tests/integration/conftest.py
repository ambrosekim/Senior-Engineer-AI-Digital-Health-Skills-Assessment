"""Integration-suite fixtures.

These tests hit a real Postgres/pgvector instance and a real Ollama server —
started via ``docker compose up -d relational_db ollama`` (or the full stack).
To avoid ever touching data ingested through the running ``backend``
container, this suite:

* creates and uses its own dedicated database (``rag_test`` by default) on
  the same Postgres server, leaving the app's ``postgres`` database untouched;
* runs the FastAPI app in-process over an ASGI transport, with its own
  session factory bound to that dedicated database;
* truncates its own tables between tests so runs are repeatable.

Connection details default to this repo's docker-compose.yaml host-mapped
ports and can be overridden with the ``TEST_*`` environment variables below,
e.g. if Ollama is mapped to a non-default host port locally.
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock

import asyncpg
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import SCHEMA_STATEMENTS, get_session, settings
from app.main import app

TEST_POSTGRES_HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
TEST_POSTGRES_PORT = int(os.environ.get("TEST_POSTGRES_PORT", "5433"))
TEST_POSTGRES_USER = os.environ.get("TEST_POSTGRES_USER", "postgres")
TEST_POSTGRES_PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "postgres")
TEST_POSTGRES_DB = os.environ.get("TEST_POSTGRES_DB", "rag_test")
TEST_OLLAMA_HOST = os.environ.get("TEST_OLLAMA_HOST", "http://localhost:11434")

_READINESS_TIMEOUT_SECONDS = 180
_READINESS_POLL_SECONDS = 2


def _test_database_url() -> URL:
    return URL.create(
        drivername="postgresql+asyncpg",
        username=TEST_POSTGRES_USER,
        password=TEST_POSTGRES_PASSWORD,
        host=TEST_POSTGRES_HOST,
        port=TEST_POSTGRES_PORT,
        database=TEST_POSTGRES_DB,
    )


async def _ensure_test_database_exists():
    conn = await asyncpg.connect(
        host=TEST_POSTGRES_HOST,
        port=TEST_POSTGRES_PORT,
        user=TEST_POSTGRES_USER,
        password=TEST_POSTGRES_PASSWORD,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_POSTGRES_DB)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_POSTGRES_DB}"')
    finally:
        await conn.close()


def _wait_for_ollama_models(required_models: list[str]) -> None:
    """Poll Ollama's /api/tags until the models this suite needs are pulled.

    Avoids a fixed sleep: a fresh ``docker compose up -d ollama`` can take a
    while to pull models the first time, but usually needs no wait at all.
    """
    deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{TEST_OLLAMA_HOST}/api/tags", timeout=5.0)
            response.raise_for_status()
            available = {m["name"].split(":")[0] for m in response.json().get("models", [])}
            if all(model in available for model in required_models):
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(_READINESS_POLL_SECONDS)

    pytest.fail(
        f"Ollama at {TEST_OLLAMA_HOST} did not report models {required_models} ready "
        f"within {_READINESS_TIMEOUT_SECONDS}s (last error: {last_error}). "
        "Make sure `docker compose up -d ollama` has finished pulling models."
    )


@pytest.fixture(scope="session", autouse=True)
def wait_for_services():
    """Session-wide readiness gate: real Postgres reachable, real Ollama models pulled."""
    deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
    last_error = None
    while time.monotonic() < deadline:
        try:
            asyncio.run(_ensure_test_database_exists())
            break
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            time.sleep(_READINESS_POLL_SECONDS)
    else:
        pytest.fail(
            f"Postgres at {TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT} was not reachable within "
            f"{_READINESS_TIMEOUT_SECONDS}s (last error: {last_error}). "
            "Make sure `docker compose up -d relational_db` is running."
        )

    _wait_for_ollama_models([settings.ollama_embed_model, settings.ollama_chat_model])


@pytest.fixture(scope="session")
def test_engine(wait_for_services):
    # NullPool: each checkout opens a fresh asyncpg connection and closes it
    # on return, so no connection ever outlives the event loop it was opened
    # on (pytest-asyncio gives each test function its own loop by default).
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)

    async def _init_schema():
        statements = [s.format(embedding_dim=settings.embedding_dim) for s in SCHEMA_STATEMENTS]
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))

    asyncio.run(_init_schema())
    # The connection opened above is bound to the throwaway loop `asyncio.run`
    # just closed; drop it so the pool opens fresh connections on the actual
    # per-test event loop the async fixtures below run on.
    asyncio.run(engine.dispose())
    yield engine
    asyncio.run(engine.dispose())


@pytest.fixture(scope="session")
def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _point_settings_at_real_ollama():
    """Ensure the live Ollama host/port for this environment is used, even if
    it differs from the Settings default baked in at app import time."""
    original_host = settings.ollama_host
    settings.ollama_host = TEST_OLLAMA_HOST
    yield
    settings.ollama_host = original_host


@pytest.fixture
async def db_session(test_session_factory):
    async with test_session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def _clean_tables(test_engine):
    """Truncate this suite's own tables before every test so runs are repeatable."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE pdf_documents, chunks CASCADE"))
    yield


@pytest.fixture
async def async_client(test_session_factory, monkeypatch):
    # Schema setup already happened in the `test_engine` fixture, so the real
    # app startup (which would connect the *global* engine, still pointed at
    # placeholder creds from the root conftest) is skipped entirely here.
    monkeypatch.setattr("app.main.init_db", AsyncMock())

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
