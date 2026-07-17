from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import DocumentVersion, Node, QAGeneration
from app.schemas.staleness import GenerationStaleness, NodeStalenessDetail
from app.services.selections import get_selection

STALENESS_LIMITATIONS = (
    "Staleness is determined solely by content-hash equality on matched "
    "section paths. A one-word wording change and a critical specification "
    "change both produce a new hash and are treated identically as stale. "
    "Renumbered sections (path changes) appear as removed rather than renamed. "
    "This check does not evaluate whether test case wording still semantically "
    "matches the updated requirement."
)


def _load_snapshot(raw_json: str) -> list[dict[str, Any]]:
    data = json.loads(raw_json)
    if not isinstance(data, list):
        raise ValueError("source_snapshot_json must be a JSON list")
    return data


def _resolve_target_version(
    db: Session,
    *,
    document_id: int,
    source_version_id: int,
    target_version_id: int | None,
) -> DocumentVersion:
    if target_version_id is not None:
        version = db.get(DocumentVersion, target_version_id)
        if version is None or version.document_id != document_id:
            raise LookupError(
                f"Target version {target_version_id} not found for document {document_id}"
            )
        return version

    latest = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.ingested_at.desc(), DocumentVersion.id.desc())
        .first()
    )
    if latest is None:
        raise LookupError(f"No versions found for document {document_id}")
    return latest


def _index_nodes_by_path(nodes: list[Node]) -> dict[str, Node]:
    indexed: dict[str, Node] = {}
    for node in nodes:
        if node.section_path is None:
            continue
        indexed[node.section_path] = node
    return indexed


def evaluate_generation_staleness(
    db: Session,
    generation_id: int,
    *,
    target_version_id: int | None = None,
) -> GenerationStaleness:
    """
    Compare a generation's source hash snapshot against a target document version.

    Default target is the latest ingested version of the same document.
    """
    generation = db.get(QAGeneration, generation_id)
    if generation is None:
        raise LookupError(f"Generation not found: {generation_id}")

    selection = get_selection(db, generation.selection_id)
    source_version = db.get(DocumentVersion, selection.version_id)
    if source_version is None:
        raise LookupError(f"Source version not found for selection {selection.id}")

    target_version = _resolve_target_version(
        db,
        document_id=source_version.document_id,
        source_version_id=source_version.id,
        target_version_id=target_version_id,
    )

    snapshot = _load_snapshot(generation.source_snapshot_json)
    target_nodes = (
        db.query(Node).filter(Node.version_id == target_version.id).all()
    )
    target_by_path = _index_nodes_by_path(target_nodes)

    details: list[NodeStalenessDetail] = []
    any_stale = False

    for entry in snapshot:
        section_path = entry.get("section_path")
        hash_at_generation = entry.get("content_hash", "")
        heading = entry.get("heading")

        if section_path is None:
            # Root/title nodes are not used for cross-version matching.
            continue

        current = target_by_path.get(section_path)
        if current is None:
            any_stale = True
            details.append(
                NodeStalenessDetail(
                    section_path=section_path,
                    heading=heading,
                    status="stale_removed",
                    hash_at_generation=hash_at_generation,
                    hash_in_target=None,
                    reason=f"Section {section_path} no longer exists in target version",
                )
            )
            continue

        if current.content_hash == hash_at_generation:
            details.append(
                NodeStalenessDetail(
                    section_path=section_path,
                    heading=heading or current.heading,
                    status="up_to_date",
                    hash_at_generation=hash_at_generation,
                    hash_in_target=current.content_hash,
                    reason="Content hash matches target version",
                )
            )
        else:
            any_stale = True
            details.append(
                NodeStalenessDetail(
                    section_path=section_path,
                    heading=heading or current.heading,
                    status="stale_modified",
                    hash_at_generation=hash_at_generation,
                    hash_in_target=current.content_hash,
                    reason=(
                        f"Content hash changed for section {section_path} "
                        "since generation"
                    ),
                )
            )

    return GenerationStaleness(
        generation_id=generation.id,
        selection_id=generation.selection_id,
        source_version_id=source_version.id,
        target_version_id=target_version.id,
        status="stale" if any_stale else "up_to_date",
        node_details=details,
        limitations=STALENESS_LIMITATIONS,
    )
