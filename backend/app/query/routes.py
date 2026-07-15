"""Routes for the RAG query endpoint: embed, retrieve, generate."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, settings
from app.documents.embeddings import EmbeddingError, embed_texts, to_pgvector_literal
from app.query.ollama_chat import ChatError, generate_answer
from app.query.schemas import QueryRequest, QueryResponse, SourceChunk

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["query"])

_SIMILARITY_SQL = """
    SELECT c.content, c.page_number, c.chunk_index, d.filename,
           1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
    FROM chunks c
    JOIN pdf_documents d ON d.id = c.document_id
    WHERE d.status = 'ready'
    ORDER BY c.embedding <=> CAST(:embedding AS vector)
    LIMIT :limit
"""

_NO_DOCUMENTS_ANSWER = (
    "I don't have any ingested documents ready to answer that yet. "
    "Please upload a PDF and wait for it to finish processing."
)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness check for this router. Remove freely if the app already has one."""
    return {"status": "ok"}


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest, session: AsyncSession = Depends(get_session)) -> QueryResponse:
    """Embed the question, retrieve the closest chunks, and generate a grounded answer."""
    top_k = payload.top_k or settings.top_k

    try:
        [embedding] = await embed_texts([payload.question])
    except EmbeddingError as exc:
        logger.exception("Embedding failed for query")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Embedding service error: {exc}") from exc

    try:
        rows = (
            await session.execute(
                text(_SIMILARITY_SQL),
                {"embedding": to_pgvector_literal(embedding), "limit": top_k},
            )
        ).mappings().all()
    except OperationalError as exc:
        logger.exception("Database unavailable during similarity search")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc

    sources = [
        SourceChunk(
            filename=row["filename"],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            score=float(row["score"]),
        )
        for row in rows
    ]

    if not sources:
        return QueryResponse(answer=_NO_DOCUMENTS_ANSWER, sources=[])

    try:
        answer = await generate_answer(payload.question, sources)
    except ChatError as exc:
        logger.exception("Chat generation failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Chat model error: {exc}") from exc

    return QueryResponse(answer=answer, sources=sources)
