"""Routes for PDF ingestion: upload, validate, chunk, embed, and store."""

import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, settings
from app.documents.embeddings import EmbeddingError, embed_texts, to_pgvector_literal
from app.documents.pdf_processing import chunk_pages, extract_pages, looks_like_pdf
from app.documents.schemas import DocumentUploadResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_READ_CHUNK_SIZE = 1024 * 1024  # 1MB


async def _read_upload_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in bounded chunks, aborting as soon as the size cap is
    exceeded so a single oversized upload can't exhaust server memory."""
    buffer = bytearray()
    total = 0
    while True:
        chunk = await upload.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the maximum allowed size of {max_bytes // (1024 * 1024)}MB",
            )
        buffer.extend(chunk)
    return bytes(buffer)


async def _find_existing_document(session: AsyncSession, content_hash: str) -> DocumentUploadResponse | None:
    row = (
        await session.execute(
            text("SELECT id, filename, page_count, status FROM pdf_documents WHERE content_hash = :hash"),
            {"hash": content_hash},
        )
    ).mappings().first()
    if row is None:
        return None

    chunk_count = (
        await session.execute(
            text("SELECT count(*) FROM chunks WHERE document_id = :doc_id"),
            {"doc_id": row["id"]},
        )
    ).scalar_one()
    return DocumentUploadResponse(
        document_id=str(row["id"]),
        filename=row["filename"],
        page_count=row["page_count"] or 0,
        chunk_count=chunk_count,
        status=row["status"],
        duplicate=True,
    )


async def _mark_failed(session: AsyncSession, document_id: uuid.UUID) -> None:
    await session.execute(
        text("UPDATE pdf_documents SET status = 'failed' WHERE id = :id"),
        {"id": document_id},
    )
    await session.commit()


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> DocumentUploadResponse:
    """Upload a PDF for ingestion into the RAG knowledge base.

    Validates the file is actually a PDF (content-type, extension, and magic
    bytes), enforces a size and page-count cap, deduplicates on content hash,
    then extracts text, chunks it per page, embeds each chunk via a local
    Ollama model, and stores everything in Postgres/pgvector.
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are accepted")

    filename = (file.filename or "upload.pdf").strip()[:255] or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .pdf files are accepted")

    data = await _read_upload_within_limit(file, settings.max_upload_size_bytes)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if not looks_like_pdf(data):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File is not a valid PDF")

    content_hash = hashlib.sha256(data).hexdigest()

    existing = await _find_existing_document(session, content_hash)
    if existing is not None:
        return existing

    try:
        pages = extract_pages(data, settings.max_pdf_pages)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    document_id = uuid.uuid4()
    try:
        await session.execute(
            text(
                """
                INSERT INTO pdf_documents (id, filename, content_hash, page_count, status)
                VALUES (:id, :filename, :content_hash, :page_count, 'processing')
                """
            ),
            {
                "id": document_id,
                "filename": filename,
                "content_hash": content_hash,
                "page_count": len(pages),
            },
        )
        await session.commit()
    except IntegrityError:
        # Another request ingested the same content between our lookup and insert.
        await session.rollback()
        existing = await _find_existing_document(session, content_hash)
        if existing is not None:
            return existing
        raise

    chunks = chunk_pages(pages, settings.chunk_size_chars, settings.chunk_overlap_chars)

    try:
        embeddings = await embed_texts([chunk.content for chunk in chunks])

        for chunk, vector in zip(chunks, embeddings):
            await session.execute(
                text(
                    """
                    INSERT INTO chunks (id, document_id, chunk_index, page_number, content, embedding)
                    VALUES (:id, :document_id, :chunk_index, :page_number, :content, CAST(:embedding AS vector))
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "embedding": to_pgvector_literal(vector),
                },
            )

        await session.execute(
            text("UPDATE pdf_documents SET status = 'ready' WHERE id = :id"),
            {"id": document_id},
        )
        await session.commit()
    except EmbeddingError as exc:
        logger.exception("Embedding failed for document %s", document_id)
        await session.rollback()
        await _mark_failed(session, document_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to generate embeddings for the document"
        ) from exc
    except Exception as exc:
        logger.exception("Processing failed for document %s", document_id)
        await session.rollback()
        await _mark_failed(session, document_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to process the document") from exc

    return DocumentUploadResponse(
        document_id=str(document_id),
        filename=filename,
        page_count=len(pages),
        chunk_count=len(chunks),
        status="ready",
    )
