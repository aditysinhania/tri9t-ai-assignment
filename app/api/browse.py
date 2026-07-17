from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.browse import (
    NodeChangeResponse,
    NodeDetail,
    NodeSearchResult,
    NodeSummary,
)
from app.services import browse as browse_service

router = APIRouter(tags=["browse"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get(
    "/documents/{document_id}/sections",
    response_model=list[NodeSummary],
)
def list_sections(
    document_id: int,
    version_id: int | None = Query(
        default=None,
        description="Document version id. Defaults to the latest ingested version.",
    ),
    db: Session = Depends(get_db),
) -> list[NodeSummary]:
    try:
        version = browse_service.resolve_version(db, document_id, version_id)
    except LookupError as exc:
        raise _http_error(exc) from exc

    nodes = browse_service.list_top_level_sections(db, version.id)
    return [NodeSummary.model_validate(node) for node in nodes]


@router.get("/nodes/{node_id}", response_model=NodeDetail)
def get_node(
    node_id: int,
    include_children: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> NodeDetail:
    node = browse_service.get_node(db, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    children = (
        browse_service.get_child_summaries(db, node_id) if include_children else []
    )
    detail = NodeDetail.model_validate(node)
    detail.children = [NodeSummary.model_validate(child) for child in children]
    return detail


@router.get(
    "/versions/{version_id}/nodes/search",
    response_model=list[NodeSearchResult],
)
def search_nodes(
    version_id: int,
    q: str = Query(min_length=1, description="Search headings and body text"),
    db: Session = Depends(get_db),
) -> list[NodeSearchResult]:
    from app.models import DocumentVersion

    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")

    nodes = browse_service.search_nodes(db, version_id, q)
    results: list[NodeSearchResult] = []
    for node in nodes:
        preview = " ".join(node.body.split())
        if len(preview) > 160:
            preview = preview[:157] + "..."
        results.append(
            NodeSearchResult(
                id=node.id,
                heading=node.heading,
                level=node.level,
                section_path=node.section_path,
                content_hash=node.content_hash,
                position=node.position,
                parent_id=node.parent_id,
                body_preview=preview,
            )
        )
    return results


@router.get("/nodes/{node_id}/changes", response_model=NodeChangeResponse)
def get_node_changes(
    node_id: int,
    other_version_id: int | None = Query(
        default=None,
        description="Version to compare against. Defaults to the latest other version.",
    ),
    db: Session = Depends(get_db),
) -> NodeChangeResponse:
    try:
        change, base_version_id, compare_version_id = (
            browse_service.compare_node_across_versions(
                db, node_id, other_version_id
            )
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc

    return NodeChangeResponse(
        section_path=change.section_path,
        status=change.status,
        base_node_id=change.base_node_id,
        compare_node_id=change.compare_node_id,
        heading_before=change.heading_before,
        heading_after=change.heading_after,
        hash_before=change.hash_before,
        hash_after=change.hash_after,
        summary=change.summary,
        base_version_id=base_version_id,
        compare_version_id=compare_version_id,
    )
