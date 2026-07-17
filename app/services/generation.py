from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.mongo import GenerationStore
from app.llm.provider import (
    LLMProvider,
    QAGenerationOutput,
    parse_and_validate_qa_output,
)
from app.models import QAGeneration
from app.services.selections import get_selection


class LLMGenerationError(Exception):
    """Raised when the LLM cannot produce valid structured output after retries."""

    def __init__(self, message: str, *, attempts: int, last_error: str):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


def reconstruct_selection_text(selection) -> tuple[str, list[dict[str, Any]]]:
    """Rebuild ordered manual text and a hash snapshot for the selection."""
    chunks: list[str] = []
    snapshot: list[dict[str, Any]] = []

    for link in sorted(selection.node_links, key=lambda item: item.position):
        node = link.node
        path = node.section_path or "ROOT"
        header = f"## {path} {node.heading}".strip()
        body = node.body.strip()
        chunk = header if not body else f"{header}\n{body}"
        chunks.append(chunk)
        snapshot.append(
            {
                "node_id": node.id,
                "section_path": node.section_path,
                "heading": node.heading,
                "content_hash": node.content_hash,
                "position": link.position,
            }
        )

    return "\n\n".join(chunks), snapshot


def _generate_validated_output(
    llm: LLMProvider,
    *,
    manual_text: str,
    max_retries: int,
) -> tuple[QAGenerationOutput, int]:
    attempts = max_retries + 1
    last_error = "unknown error"

    for attempt in range(1, attempts + 1):
        try:
            raw = llm.generate_qa_json(manual_text=manual_text, attempt=attempt)
            return parse_and_validate_qa_output(raw), attempt
        except (ValueError, RuntimeError) as exc:
            last_error = str(exc)

    raise LLMGenerationError(
        "Failed to obtain valid QA JSON from the LLM",
        attempts=attempts,
        last_error=last_error,
    )


def generate_qa_for_selection(
    db: Session,
    *,
    selection_id: int,
    llm: LLMProvider,
    store: GenerationStore,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """
    Create a new QA generation run for a selection.

    Duplicate submissions always create a new run (audit-friendly policy).
    Invalid LLM output is never persisted.
    """
    settings = get_settings()
    retries = settings.llm_max_retries if max_retries is None else max_retries

    selection = get_selection(db, selection_id)
    manual_text, snapshot = reconstruct_selection_text(selection)
    if not manual_text.strip():
        raise ValueError("Selection has no textual content to generate from")

    output, attempts_used = _generate_validated_output(
        llm, manual_text=manual_text, max_retries=retries
    )

    created_at = datetime.now(timezone.utc)
    mongo_payload = {
        "selection_id": selection.id,
        "version_id": selection.version_id,
        "created_at": created_at.isoformat(),
        "source_nodes": snapshot,
        "reconstructed_text": manual_text,
        "test_cases": [case.model_dump() for case in output.test_cases],
        "attempts_used": attempts_used,
    }
    mongo_id = store.insert(mongo_payload)

    record = QAGeneration(
        selection_id=selection.id,
        mongo_id=mongo_id,
        source_snapshot_json=json.dumps(snapshot),
        test_case_count=len(output.test_cases),
        created_at=created_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "selection_id": record.selection_id,
        "mongo_id": record.mongo_id,
        "test_case_count": record.test_case_count,
        "created_at": record.created_at,
        "attempts_used": attempts_used,
        "source_nodes": snapshot,
        "test_cases": [case.model_dump() for case in output.test_cases],
    }
