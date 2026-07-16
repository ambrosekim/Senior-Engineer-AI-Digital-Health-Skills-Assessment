from unittest.mock import AsyncMock

import pytest

from app.documents.embeddings import EmbeddingError
from app.query.ollama_chat import ChatError
from app.query.routes import _NO_DOCUMENTS_ANSWER

pytestmark = pytest.mark.unit


def _similarity_row(content="relevant chunk", filename="doc.pdf", page_number=2, chunk_index=0, score=0.87):
    return {
        "content": content,
        "page_number": page_number,
        "chunk_index": chunk_index,
        "filename": filename,
        "score": score,
    }


def test_query_rejects_empty_question(client):
    response = client.post("/api/query", json={"question": ""})

    assert response.status_code == 422


def test_query_rejects_top_k_out_of_range(client):
    response = client.post("/api/query", json={"question": "hello", "top_k": 50})

    assert response.status_code == 422


def test_query_returns_grounded_answer_with_sources(client, fake_session, monkeypatch):
    fake_session.similarity_rows = [_similarity_row(), _similarity_row(content="second chunk", chunk_index=1)]
    monkeypatch.setattr("app.query.routes.embed_texts", AsyncMock(return_value=[[0.1] * 384]))
    generate_mock = AsyncMock(return_value="Grounded answer citing doc.pdf page 2.")
    monkeypatch.setattr("app.query.routes.generate_answer", generate_mock)

    response = client.post("/api/query", json={"question": "What does the policy say?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Grounded answer citing doc.pdf page 2."
    assert len(body["sources"]) == 2
    assert body["sources"][0]["filename"] == "doc.pdf"
    assert body["sources"][0]["score"] == 0.87
    generate_mock.assert_awaited_once()


def test_query_empty_retrieval_returns_fallback_without_calling_chat_model(client, fake_session, monkeypatch):
    fake_session.similarity_rows = []
    monkeypatch.setattr("app.query.routes.embed_texts", AsyncMock(return_value=[[0.1] * 384]))
    generate_mock = AsyncMock()
    monkeypatch.setattr("app.query.routes.generate_answer", generate_mock)

    response = client.post("/api/query", json={"question": "Anything in the knowledge base?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == _NO_DOCUMENTS_ANSWER
    assert body["sources"] == []
    generate_mock.assert_not_called()


def test_query_embedding_service_down_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        "app.query.routes.embed_texts", AsyncMock(side_effect=EmbeddingError("connection refused"))
    )

    response = client.post("/api/query", json={"question": "hello"})

    assert response.status_code == 502
    assert "Embedding service error" in response.json()["detail"]


def test_query_chat_model_down_returns_502(client, fake_session, monkeypatch):
    fake_session.similarity_rows = [_similarity_row()]
    monkeypatch.setattr("app.query.routes.embed_texts", AsyncMock(return_value=[[0.1] * 384]))
    monkeypatch.setattr(
        "app.query.routes.generate_answer", AsyncMock(side_effect=ChatError("model unreachable"))
    )

    response = client.post("/api/query", json={"question": "hello"})

    assert response.status_code == 502
    assert "Chat model error" in response.json()["detail"]


def test_query_database_error_returns_503(client, fake_session, monkeypatch):
    fake_session.raise_operational_error = True
    monkeypatch.setattr("app.query.routes.embed_texts", AsyncMock(return_value=[[0.1] * 384]))

    response = client.post("/api/query", json={"question": "hello"})

    assert response.status_code == 503
    assert "Database unavailable" in response.json()["detail"]


def test_query_uses_default_top_k_when_not_provided(client, fake_session, monkeypatch):
    fake_session.similarity_rows = [_similarity_row()]
    monkeypatch.setattr("app.query.routes.embed_texts", AsyncMock(return_value=[[0.1] * 384]))
    monkeypatch.setattr("app.query.routes.generate_answer", AsyncMock(return_value="answer"))

    response = client.post("/api/query", json={"question": "hello"})

    assert response.status_code == 200
