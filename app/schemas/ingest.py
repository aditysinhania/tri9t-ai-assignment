from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Ingest a local PDF as a new document version."""

    pdf_path: str = Field(
        description="Path to the PDF, absolute or relative to the project root "
        "(e.g. data/ct200_manual.pdf).",
    )
    version_label: str = Field(
        min_length=1,
        max_length=64,
        description="Label for this version (e.g. v1, v2).",
    )
    document_title: str | None = Field(
        default=None,
        description="Optional override; defaults to the parsed PDF title.",
    )


class IngestResponse(BaseModel):
    document_id: int
    version_id: int
    version_label: str
    source_filename: str
    node_count: int
    ingested_at: datetime
