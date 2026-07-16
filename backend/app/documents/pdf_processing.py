"""PDF text extraction and chunking.

Chunking is done per-page (rather than over the concatenated document text) so
that each chunk can be reliably attributed to a single page number.
"""

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

PDF_MAGIC = b"%PDF-"

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    page_number: int
    content: str


def looks_like_pdf(data: bytes) -> bool:
    """Cheap magic-byte sniff; never trust a client-supplied Content-Type alone."""
    return data[:5] == PDF_MAGIC


def extract_pages(data: bytes, max_pages: int) -> list[str]:
    """Return the extracted text of each page, in order.

    Raises ValueError (caller maps this to a 422) for anything that makes the
    upload unprocessable: corrupt file, unsupported encryption, no pages, or a
    page count above ``max_pages`` (guards against a single upload consuming
    unbounded parsing/embedding time and storage).
    """
    try:
        reader = PdfReader(BytesIO(data))
    except (PdfReadError, ValueError) as exc:
        raise ValueError("File is not a valid or supported PDF") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("Encrypted PDFs are not supported") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF has no pages")
    if page_count > max_pages:
        raise ValueError(f"PDF exceeds the maximum of {max_pages} pages")

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def chunk_pages(pages: list[str], chunk_size: int, overlap: int) -> list[TextChunk]:
    """Split each page's text into overlapping character-window chunks.

    Breaks are snapped to the nearest preceding space so words aren't split.
    """
    chunks: list[TextChunk] = []
    chunk_index = 0

    for page_number, raw_text in enumerate(pages, start=1):
        text = _normalize(raw_text)
        if not text:
            continue

        length = len(text)
        start = 0
        while start < length:
            end = min(start + chunk_size, length)
            if end < length:
                snapped = text.rfind(" ", start, end)
                if snapped > start:
                    end = snapped

            content = text[start:end].strip()
            if content:
                chunks.append(TextChunk(chunk_index=chunk_index, page_number=page_number, content=content))
                chunk_index += 1

            if end >= length:
                break
            start = max(end - overlap, start + 1)

    return chunks
