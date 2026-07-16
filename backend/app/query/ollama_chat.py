"""Grounded answer generation via a local Ollama chat model."""

import httpx

from app.db import settings
from app.query.schemas import SourceChunk

_SYSTEM_PROMPT = (
    "You are a careful assistant answering questions using only the context provided below. "
    "If the context does not contain the answer, say you don't know instead of guessing. "
    "Reference the filename and page number of the source(s) you used when relevant."
)


class ChatError(RuntimeError):
    """Raised when the chat model is unreachable or returns bad data."""


def _build_context(sources: list[SourceChunk]) -> str:
    return "\n\n".join(f"[{source.filename}, page {source.page_number}]\n{source.content}" for source in sources)


async def generate_answer(question: str, sources: list[SourceChunk]) -> str:
    """Call Ollama's /api/chat with retrieved chunks injected as context and wait for the full reply."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Context:\n{_build_context(sources)}\n\nQuestion: {question}"},
    ]

    async with httpx.AsyncClient(base_url=settings.ollama_host, timeout=120.0) as client:
        try:
            response = await client.post(
                "/api/chat",
                json={"model": settings.ollama_chat_model, "messages": messages, "stream": False},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ChatError(f"Chat service request failed: {exc}") from exc

    content = response.json().get("message", {}).get("content")
    if not content:
        raise ChatError("Chat service returned an unexpected response shape")
    return content
