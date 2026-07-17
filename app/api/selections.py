from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.selections import SelectionCreate, SelectionResponse
from app.services import selections as selection_service

router = APIRouter(tags=["selections"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.post("/selections", response_model=SelectionResponse, status_code=201)
def create_selection(
    payload: SelectionCreate,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    try:
        selection = selection_service.create_selection(
            db,
            name=payload.name,
            version_id=payload.version_id,
            node_ids=payload.node_ids,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return SelectionResponse.model_validate(
        selection_service.selection_to_payload(selection)
    )


@router.get("/selections/{selection_id}", response_model=SelectionResponse)
def get_selection(
    selection_id: int,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    try:
        selection = selection_service.get_selection(db, selection_id)
    except LookupError as exc:
        raise _http_error(exc) from exc
    return SelectionResponse.model_validate(
        selection_service.selection_to_payload(selection)
    )


@router.get("/selections", response_model=list[SelectionResponse])
def list_selections(
    version_id: int | None = Query(
        default=None,
        description="Optional filter to selections pinned to a version.",
    ),
    db: Session = Depends(get_db),
) -> list[SelectionResponse]:
    try:
        selections = selection_service.list_selections(db, version_id=version_id)
    except LookupError as exc:
        raise _http_error(exc) from exc
    return [
        SelectionResponse.model_validate(
            selection_service.selection_to_payload(selection)
        )
        for selection in selections
    ]
