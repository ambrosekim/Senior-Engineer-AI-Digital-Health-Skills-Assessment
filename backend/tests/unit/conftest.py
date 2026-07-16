"""Unit-suite fixtures: an in-memory fake pgvector/Postgres layer and a wired TestClient.

No unit test opens a real database connection or calls a real Ollama server —
``get_session`` is overridden with :class:`FakeSession` and Ollama calls are
monkeypatched per-test at the point of use (``embed_texts`` / ``generate_answer``).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


class FakeResult:
    """Stands in for a SQLAlchemy ``CursorResult``, supporting the subset of the
    API the routes actually use (``.mappings().first()/.all()`` and ``.scalar_one()``)."""

    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return self._rows[0] if self._rows else 0


class FakeSession:
    """A minimal in-memory stand-in for the pgvector-backed AsyncSession.

    Understands exactly the SQL statements issued by the documents/query
    routers today; raises loudly on anything else so a route change that adds
    a new query is caught by a failing test rather than silently no-op'ing.
    """

    def __init__(self):
        self.documents: dict = {}
        self.chunks: list = []
        self.similarity_rows: list = []
        self.raise_operational_error = False
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}

        if "SELECT id, filename, page_count, status FROM pdf_documents WHERE content_hash" in sql:
            for doc in self.documents.values():
                if doc["content_hash"] == params["hash"]:
                    return FakeResult([doc])
            return FakeResult([])

        if "SELECT count(*) FROM chunks WHERE document_id" in sql:
            count = sum(1 for c in self.chunks if c["document_id"] == params["doc_id"])
            return FakeResult([count])

        if sql.strip().startswith("INSERT INTO pdf_documents"):
            self.documents[params["id"]] = {
                "id": params["id"],
                "filename": params["filename"],
                "content_hash": params["content_hash"],
                "page_count": params["page_count"],
                "status": "processing",
                "created_at": datetime.now(timezone.utc),
            }
            return FakeResult([])

        if sql.strip().startswith("INSERT INTO chunks"):
            self.chunks.append(
                {
                    "id": params["id"],
                    "document_id": params["document_id"],
                    "chunk_index": params["chunk_index"],
                    "page_number": params["page_number"],
                    "content": params["content"],
                    "embedding": params["embedding"],
                }
            )
            return FakeResult([])

        if "UPDATE pdf_documents SET status = 'ready'" in sql:
            self.documents[params["id"]]["status"] = "ready"
            return FakeResult([])

        if "UPDATE pdf_documents SET status = 'failed'" in sql:
            self.documents[params["id"]]["status"] = "failed"
            return FakeResult([])

        if "FROM pdf_documents d" in sql and "LEFT JOIN chunks" in sql:
            rows = []
            for doc in self.documents.values():
                chunk_count = sum(1 for c in self.chunks if c["document_id"] == doc["id"])
                rows.append({**doc, "chunk_count": chunk_count})
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return FakeResult(rows)

        if "FROM chunks c" in sql and "JOIN pdf_documents d" in sql:
            if self.raise_operational_error:
                raise OperationalError("simulated DB outage", {}, None)
            return FakeResult(self.similarity_rows)

        raise AssertionError(f"FakeSession received an unexpected statement: {sql!r}")

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def client(fake_session, monkeypatch):
    monkeypatch.setattr("app.main.init_db", AsyncMock())

    from app.db import get_session
    from app.main import app

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
