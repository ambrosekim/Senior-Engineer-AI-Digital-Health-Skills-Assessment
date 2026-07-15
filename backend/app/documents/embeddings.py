"""Embedding generation via a local Ollama server (no external API key required)."""

import httpx

from app.db import settings

_BATCH_SIZE = 32


class EmbeddingError(RuntimeError):
    """Raised when the embedding service is unreachable or returns bad data."""


def to_pgvector_literal(vector: list[float]) -> str:
    """Format floats as a pgvector text literal, e.g. '[0.1,-0.2]'.

    Fixed-point (not repr's scientific notation) since pgvector's input
    parser does not accept exponent notation.
    """
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, calling Ollama in fixed-size sub-batches."""
    if not texts:
        return []

    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(base_url=settings.ollama_host, timeout=60.0) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            try:
                response = await client.post(
                    "/api/embed",
                    json={"model": settings.ollama_embed_model, "input": batch},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"Embedding service request failed: {exc}") from exc

            payload = response.json()
            batch_embeddings = payload.get("embeddings")
            if not batch_embeddings or len(batch_embeddings) != len(batch):
                raise EmbeddingError("Embedding service returned an unexpected response shape")
            for vector in batch_embeddings:
                if len(vector) != settings.embedding_dim:
                    raise EmbeddingError(
                        f"Embedding dimension mismatch: expected {settings.embedding_dim}, got {len(vector)}"
                    )
            embeddings.extend(batch_embeddings)

    return embeddings
