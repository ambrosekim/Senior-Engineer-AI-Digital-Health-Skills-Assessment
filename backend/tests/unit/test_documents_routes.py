from unittest.mock import AsyncMock

import pytest

from app.db import settings
from app.documents.embeddings import EmbeddingError
from tests.pdf_fixtures import build_minimal_pdf

pytestmark = pytest.mark.unit

VALID_PDF = build_minimal_pdf(["Community health worker guidelines.", "Chapter one."])


def _upload(client, data=VALID_PDF, filename="doc.pdf", content_type="application/pdf"):
    return client.post("/documents/upload", files={"file": (filename, data, content_type)})


def test_upload_rejects_non_pdf_content_type(client):
    response = _upload(client, content_type="text/plain")

    assert response.status_code == 415
    assert "Only PDF files are accepted" in response.json()["detail"]


def test_upload_rejects_non_pdf_extension(client):
    response = _upload(client, filename="doc.txt")

    assert response.status_code == 415
    assert "Only .pdf files are accepted" in response.json()["detail"]


def test_upload_rejects_empty_file(client):
    response = _upload(client, data=b"")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_upload_rejects_non_pdf_magic_bytes(client):
    response = _upload(client, data=b"not really a pdf")

    assert response.status_code == 415
    assert "not a valid PDF" in response.json()["detail"]


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_bytes", 10)

    response = _upload(client, data=VALID_PDF)

    assert response.status_code == 413


def test_upload_rejects_corrupt_pdf_structure(client):
    response = _upload(client, data=b"%PDF-1.4\nthis is not a real pdf structure")

    assert response.status_code == 422


def test_upload_success_stores_chunks_and_returns_ready(client, fake_session, monkeypatch):
    embed_mock = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
    monkeypatch.setattr("app.documents.routes.embed_texts", embed_mock)

    response = _upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["filename"] == "doc.pdf"
    assert body["chunk_count"] > 0
    assert body["duplicate"] is False
    embed_mock.assert_awaited_once()

    [doc] = fake_session.documents.values()
    assert doc["status"] == "ready"


def test_upload_duplicate_content_short_circuits_embedding(client, monkeypatch):
    embed_mock = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
    monkeypatch.setattr("app.documents.routes.embed_texts", embed_mock)

    first = _upload(client)
    assert first.status_code == 201

    second = _upload(client)
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["document_id"] == first.json()["document_id"]

    embed_mock.assert_awaited_once()  # not called again for the duplicate


def test_upload_embedding_failure_marks_document_failed(client, fake_session, monkeypatch):
    embed_mock = AsyncMock(side_effect=EmbeddingError("ollama unreachable"))
    monkeypatch.setattr("app.documents.routes.embed_texts", embed_mock)

    response = _upload(client)

    assert response.status_code == 502
    [doc] = fake_session.documents.values()
    assert doc["status"] == "failed"


def test_list_documents_empty(client):
    response = client.get("/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_uploaded_items(client, monkeypatch):
    embed_mock = AsyncMock(return_value=[[0.1] * 384, [0.2] * 384])
    monkeypatch.setattr("app.documents.routes.embed_texts", embed_mock)
    _upload(client)

    response = client.get("/documents")

    assert response.status_code == 200
    [item] = response.json()
    assert item["filename"] == "doc.pdf"
    assert item["status"] == "ready"
    assert item["chunk_count"] > 0
