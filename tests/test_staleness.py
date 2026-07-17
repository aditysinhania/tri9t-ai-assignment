"""Staleness detection tests — hash snapshot vs newer document version."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.db.mongo import InMemoryGenerationStore
from app.llm.provider import ScriptedLLMProvider
from app.models import Document, Node, QAGeneration, SelectionNode
from app.services.generation import generate_qa_for_selection
from app.services.ingestion import ingest_pdf
from app.services.selections import create_selection
from app.services.staleness import evaluate_generation_staleness

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"
V2_PDF = PROJECT_ROOT / "data" / "ct200_manual_v2.pdf"

VALID_PAYLOAD = {
    "test_cases": [
        {
            "title": "Case A",
            "steps": ["Step 1"],
            "expected_result": "Result A",
            "source_section_paths": ["1.1"],
        },
        {
            "title": "Case B",
            "steps": ["Step 1"],
            "expected_result": "Result B",
            "source_section_paths": ["2.1.1.1"],
        },
        {
            "title": "Case C",
            "steps": ["Step 1"],
            "expected_result": "Result C",
            "source_section_paths": ["4.2"],
        },
    ]
}


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    assert Document.__tablename__
    assert QAGeneration.__tablename__
    assert SelectionNode.__tablename__
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _node_id(db: Session, version_id: int, section_path: str) -> int:
    return (
        db.query(Node)
        .filter(Node.version_id == version_id, Node.section_path == section_path)
        .one()
        .id
    )


def _create_generation(db: Session, version, paths: list[str]) -> int:
    selection = create_selection(
        db,
        name="Staleness probe",
        version_id=version.id,
        node_ids=[_node_id(db, version.id, path) for path in paths],
    )
    llm = ScriptedLLMProvider([json.dumps(VALID_PAYLOAD)])
    store = InMemoryGenerationStore()
    result = generate_qa_for_selection(
        db,
        selection_id=selection.id,
        llm=llm,
        store=store,
    )
    return result["id"]


def test_unchanged_selection_is_up_to_date_against_v2(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db_session, V2_PDF, version_label="v2")
    generation_id = _create_generation(db_session, v1, ["1.1"])

    report = evaluate_generation_staleness(
        db_session, generation_id, target_version_id=v2.id
    )

    assert report.status == "up_to_date"
    assert report.source_version_id == v1.id
    assert report.target_version_id == v2.id
    assert len(report.node_details) == 1
    assert report.node_details[0].section_path == "1.1"
    assert report.node_details[0].status == "up_to_date"
    assert "wording change" in report.limitations


def test_modified_section_marks_generation_stale(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db_session, V2_PDF, version_label="v2")
    generation_id = _create_generation(db_session, v1, ["2.1.1.1"])

    report = evaluate_generation_staleness(
        db_session, generation_id, target_version_id=v2.id
    )

    assert report.status == "stale"
    detail = report.node_details[0]
    assert detail.section_path == "2.1.1.1"
    assert detail.status == "stale_modified"
    assert detail.hash_at_generation != detail.hash_in_target


def test_mixed_selection_stale_if_any_source_node_changed(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db_session, V2_PDF, version_label="v2")
    generation_id = _create_generation(db_session, v1, ["1.1", "2.1.1.1"])

    report = evaluate_generation_staleness(
        db_session, generation_id, target_version_id=v2.id
    )

    assert report.status == "stale"
    by_path = {item.section_path: item.status for item in report.node_details}
    assert by_path["1.1"] == "up_to_date"
    assert by_path["2.1.1.1"] == "stale_modified"


def test_defaults_to_latest_version_when_target_not_specified(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    ingest_pdf(db_session, V2_PDF, version_label="v2")
    generation_id = _create_generation(db_session, v1, ["2.1.1.1"])

    report = evaluate_generation_staleness(db_session, generation_id)

    assert report.status == "stale"
    assert report.target_version_id != v1.id


def test_new_section_in_v2_does_not_affect_v1_generation(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db_session, V2_PDF, version_label="v2")
    generation_id = _create_generation(db_session, v1, ["5.1"])

    report = evaluate_generation_staleness(
        db_session, generation_id, target_version_id=v2.id
    )

    assert report.status == "up_to_date"
    assert all(d.section_path != "5.3" for d in report.node_details)
