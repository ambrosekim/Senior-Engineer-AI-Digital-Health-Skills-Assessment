"""End-to-end RAG flow against real Postgres/pgvector and real Ollama.

Requires ``docker compose up -d relational_db ollama`` (or the full stack)
to be running first — see README.md for exact prerequisites.
"""

import pytest
from sqlalchemy import text

from tests.pdf_fixtures import build_minimal_pdf

pytestmark = pytest.mark.integration

TEST_DOCUMENT = build_minimal_pdf(
    [
        "Community health workers in Kenya provide basic primary care services.",
        "The national community health policy emphasizes universal health coverage.",
    ]
)


async def _upload_test_document(async_client, filename="integration_test_doc.pdf"):
    response = await async_client.post(
        "/documents/upload",
        files={"file": (filename, TEST_DOCUMENT, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_upload_ingests_document_and_stores_embeddings(async_client, db_session):
    result = await _upload_test_document(async_client)

    assert result["status"] == "ready"
    assert result["chunk_count"] > 0

    stored_count = (
        await db_session.execute(
            text("SELECT count(*) FROM chunks WHERE document_id = :id"),
            {"id": result["document_id"]},
        )
    ).scalar_one()
    assert stored_count == result["chunk_count"]

    dims = (
        await db_session.execute(
            text("SELECT vector_dims(embedding) FROM chunks WHERE document_id = :id LIMIT 1"),
            {"id": result["document_id"]},
        )
    ).scalar_one()
    assert dims == 384


async def test_uploaded_document_appears_in_listing(async_client):
    uploaded = await _upload_test_document(async_client)

    response = await async_client.get("/documents")

    assert response.status_code == 200
    documents = response.json()
    [match] = [d for d in documents if d["document_id"] == uploaded["document_id"]]
    assert match["status"] == "ready"
    assert match["chunk_count"] == uploaded["chunk_count"]


async def test_query_retrieves_relevant_chunks_from_ingested_document(async_client):
    await _upload_test_document(async_client)

    response = await async_client.post(
        "/api/query",
        json={"question": "What does Kenya's community health policy emphasize?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"], "expected the similarity search to retrieve at least one chunk"
    assert any("universal health coverage" in s["content"].lower() for s in body["sources"])
    assert all(s["filename"] == "integration_test_doc.pdf" for s in body["sources"])


async def test_query_returns_grounded_chat_answer(async_client):
    """Full pipeline: ingest -> embed -> retrieve -> real llama3.2 generation."""
    await _upload_test_document(async_client)

    response = await async_client.post(
        "/api/query",
        json={"question": "What kind of care do community health workers provide?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"].strip()
    assert body["sources"]


async def test_query_with_no_ingested_documents_returns_fallback(async_client):
    response = await async_client.post("/api/query", json={"question": "Anything ingested yet?"})

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert "don't have any ingested documents" in body["answer"]


async def test_reuploading_same_content_is_deduplicated(async_client):
    first = await _upload_test_document(async_client, filename="first.pdf")
    second = await _upload_test_document(async_client, filename="first.pdf")

    assert second["duplicate"] is True
    assert second["document_id"] == first["document_id"]
