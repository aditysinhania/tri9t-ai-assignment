from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.mongo import GenerationStore
from app.models import Node, QAGeneration
from app.services.selections import get_selection
from app.services.staleness import evaluate_generation_staleness


def _snapshot_contains_node(raw_json: str, node_id: int) -> bool:
    snapshot = json.loads(raw_json)
    return any(entry.get("node_id") == node_id for entry in snapshot)


def _build_retrieval_payload(
    db: Session,
    generation: QAGeneration,
    store: GenerationStore,
    *,
    target_version_id: int | None = None,
) -> dict[str, Any]:
    mongo_doc = store.get(generation.mongo_id)
    if mongo_doc is None:
        raise LookupError(
            f"Generation payload not found in store for mongo_id={generation.mongo_id}"
        )

    staleness = evaluate_generation_staleness(
        db,
        generation.id,
        target_version_id=target_version_id,
    )

    return {
        "id": generation.id,
        "selection_id": generation.selection_id,
        "mongo_id": generation.mongo_id,
        "test_case_count": generation.test_case_count,
        "created_at": generation.created_at,
        "attempts_used": mongo_doc.get("attempts_used", 1),
        "source_nodes": mongo_doc.get("source_nodes", []),
        "test_cases": mongo_doc.get("test_cases", []),
        "staleness_status": staleness.status,
        "source_version_id": staleness.source_version_id,
        "target_version_id": staleness.target_version_id,
        "node_staleness": [item.model_dump() for item in staleness.node_details],
        "staleness_limitations": staleness.limitations,
    }


def _build_summary(
    db: Session,
    generation: QAGeneration,
    *,
    target_version_id: int | None = None,
) -> dict[str, Any]:
    staleness = evaluate_generation_staleness(
        db,
        generation.id,
        target_version_id=target_version_id,
    )
    return {
        "id": generation.id,
        "selection_id": generation.selection_id,
        "mongo_id": generation.mongo_id,
        "test_case_count": generation.test_case_count,
        "created_at": generation.created_at,
        "staleness_status": staleness.status,
        "source_version_id": staleness.source_version_id,
        "target_version_id": staleness.target_version_id,
    }


def get_generation(
    db: Session,
    generation_id: int,
    store: GenerationStore,
    *,
    target_version_id: int | None = None,
) -> dict[str, Any]:
    generation = db.get(QAGeneration, generation_id)
    if generation is None:
        raise LookupError(f"Generation not found: {generation_id}")
    return _build_retrieval_payload(
        db, generation, store, target_version_id=target_version_id
    )


def list_generations_for_selection(
    db: Session,
    selection_id: int,
    store: GenerationStore,
    *,
    target_version_id: int | None = None,
    include_details: bool = False,
) -> list[dict[str, Any]]:
    get_selection(db, selection_id)
    generations = (
        db.query(QAGeneration)
        .filter(QAGeneration.selection_id == selection_id)
        .order_by(QAGeneration.created_at.asc(), QAGeneration.id.asc())
        .all()
    )
    if include_details:
        return [
            _build_retrieval_payload(
                db, generation, store, target_version_id=target_version_id
            )
            for generation in generations
        ]
    return [
        _build_summary(db, generation, target_version_id=target_version_id)
        for generation in generations
    ]


def list_generations_for_node(
    db: Session,
    node_id: int,
    store: GenerationStore,
    *,
    target_version_id: int | None = None,
    include_details: bool = False,
) -> list[dict[str, Any]]:
    node = db.get(Node, node_id)
    if node is None:
        raise LookupError(f"Node not found: {node_id}")

    generations = (
        db.query(QAGeneration)
        .order_by(QAGeneration.created_at.asc(), QAGeneration.id.asc())
        .all()
    )
    matched = [
        generation
        for generation in generations
        if _snapshot_contains_node(generation.source_snapshot_json, node_id)
    ]

    if include_details:
        return [
            _build_retrieval_payload(
                db, generation, store, target_version_id=target_version_id
            )
            for generation in matched
        ]
    return [
        _build_summary(db, generation, target_version_id=target_version_id)
        for generation in matched
    ]
