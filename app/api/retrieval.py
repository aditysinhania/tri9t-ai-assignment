from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.db.mongo import GenerationStore, get_generation_store
from app.schemas.retrieval import GenerationRetrievalResponse, GenerationSummary
from app.services import retrieval as retrieval_service

router = APIRouter(tags=["retrieval"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/generations/{generation_id}", response_model=GenerationRetrievalResponse)
def get_generation(
    generation_id: int,
    target_version_id: int | None = Query(
        default=None,
        description="Version to compare staleness against. Defaults to latest.",
    ),
    db: Session = Depends(get_db),
    store: GenerationStore = Depends(get_generation_store),
) -> GenerationRetrievalResponse:
    try:
        payload = retrieval_service.get_generation(
            db,
            generation_id,
            store,
            target_version_id=target_version_id,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return GenerationRetrievalResponse.model_validate(payload)


@router.get(
    "/selections/{selection_id}/generations",
    response_model=list[GenerationSummary],
)
def list_generations_for_selection(
    selection_id: int,
    target_version_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    store: GenerationStore = Depends(get_generation_store),
) -> list[GenerationSummary]:
    try:
        items = retrieval_service.list_generations_for_selection(
            db,
            selection_id,
            store,
            target_version_id=target_version_id,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return [GenerationSummary.model_validate(item) for item in items]


@router.get(
    "/nodes/{node_id}/generations",
    response_model=list[GenerationSummary],
)
def list_generations_for_node(
    node_id: int,
    target_version_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    store: GenerationStore = Depends(get_generation_store),
) -> list[GenerationSummary]:
    try:
        items = retrieval_service.list_generations_for_node(
            db,
            node_id,
            store,
            target_version_id=target_version_id,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return [GenerationSummary.model_validate(item) for item in items]
