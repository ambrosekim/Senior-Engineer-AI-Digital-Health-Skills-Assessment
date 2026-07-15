"""Pydantic schemas for the document ingestion endpoints."""

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    status: str
    duplicate: bool = False
