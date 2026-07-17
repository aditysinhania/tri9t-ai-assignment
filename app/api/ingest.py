from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Node
from app.schemas.ingest import IngestRequest, IngestResponse
from app.services.ingestion import ingest_pdf

router = APIRouter(tags=["ingest"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_pdf_path(pdf_path: str) -> Path:
    path = Path(pdf_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Keep ingestion scoped to the project tree for safety.
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            "pdf_path must point to a file inside the project directory"
        ) from exc

    if path.suffix.lower() != ".pdf":
        raise ValueError("pdf_path must be a .pdf file")

    return path


@router.post("/documents/ingest", response_model=IngestResponse, status_code=201)
def ingest_document(
    payload: IngestRequest,
    db: Session = Depends(get_db),
) -> IngestResponse:
    try:
        path = _resolve_pdf_path(payload.pdf_path)
        version = ingest_pdf(
            db,
            path,
            version_label=payload.version_label.strip(),
            document_title=payload.document_title,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Ingestion failed: {exc}"
        ) from exc

    node_count = db.query(Node).filter(Node.version_id == version.id).count()
    return IngestResponse(
        document_id=version.document_id,
        version_id=version.id,
        version_label=version.version_label,
        source_filename=version.source_filename,
        node_count=node_count,
        ingested_at=version.ingested_at,
    )
