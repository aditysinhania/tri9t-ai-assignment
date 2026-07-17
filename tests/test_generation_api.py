"""LLM QA generation tests (fake provider + in-memory Mongo store)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.generation import get_llm_provider
from app.core.database import Base, get_db
from app.db.mongo import InMemoryGenerationStore, get_generation_store
from app.llm.provider import ScriptedLLMProvider, parse_and_validate_qa_output
from app.main import app
from app.models import Document, Node, QAGeneration, SelectionNode
from app.services.ingestion import ingest_pdf
from app.services.selections import create_selection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"

VALID_PAYLOAD = {
    "test_cases": [
        {
            "title": "Verify E3 overpressure deflation",
            "steps": [
                "Simulate cuff pressure above safe limit",
                "Observe device response",
            ],
            "expected_result": "Device displays E3 and auto-deflates within 2 seconds",
            "source_section_paths": ["4.1", "4.2"],
        },
        {
            "title": "Confirm motion artifact abort",
            "steps": ["Start measurement", "Introduce motion artifact"],
            "expected_result": "Device aborts and displays E2 with retry prompt",
            "source_section_paths": ["4.2"],
        },
        {
            "title": "Check profile-scoped storage",
            "steps": ["Select User 1", "Complete a reading"],
            "expected_result": "Reading is stored against User 1",
            "source_section_paths": ["3.1", "5.1"],
        },
    ]
}


@pytest.fixture()
def client_ctx():
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
    store = InMemoryGenerationStore()

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_generation_store] = lambda: store

    client = TestClient(app)
    db = SessionLocal()
    try:
        yield client, db, store, SessionLocal
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)


def _seed_selection(db):
    version = ingest_pdf(db, V1_PDF, version_label="v1")
    node_ids = [
        db.query(Node)
        .filter(Node.version_id == version.id, Node.section_path == path)
        .one()
        .id
        for path in ("4.1", "4.2")
    ]
    selection = create_selection(
        db,
        name="Safety suite",
        version_id=version.id,
        node_ids=node_ids,
    )
    return selection


def test_parse_and_validate_accepts_valid_payload():
    raw = json.dumps(VALID_PAYLOAD)
    parsed = parse_and_validate_qa_output(raw)
    assert len(parsed.test_cases) == 3


def test_parse_and_validate_rejects_too_few_cases():
    payload = {"test_cases": VALID_PAYLOAD["test_cases"][:2]}
    with pytest.raises(ValueError):
        parse_and_validate_qa_output(json.dumps(payload))


def test_generate_retries_then_succeeds(client_ctx):
    client, db, store, _ = client_ctx
    selection = _seed_selection(db)

    provider = ScriptedLLMProvider(
        [
            "not-json",
            json.dumps(VALID_PAYLOAD),
        ]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(f"/selections/{selection.id}/generations")
    assert response.status_code == 201
    body = response.json()
    assert body["test_case_count"] == 3
    assert body["attempts_used"] == 2
    assert body["mongo_id"] in store.documents
    assert len(body["test_cases"]) == 3
    assert provider.calls == 2

    rows = db.query(QAGeneration).all()
    assert len(rows) == 1
    assert rows[0].mongo_id == body["mongo_id"]


def test_generate_fails_after_retries_without_persisting(client_ctx):
    client, db, store, _ = client_ctx
    selection = _seed_selection(db)

    provider = ScriptedLLMProvider(["bad", "still-bad", "also-bad"])
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.post(f"/selections/{selection.id}/generations")
    assert response.status_code == 502
    assert db.query(QAGeneration).count() == 0
    assert store.documents == {}


def test_duplicate_submit_creates_new_generation(client_ctx):
    client, db, store, _ = client_ctx
    selection = _seed_selection(db)

    provider = ScriptedLLMProvider(
        [json.dumps(VALID_PAYLOAD), json.dumps(VALID_PAYLOAD)]
    )
    app.dependency_overrides[get_llm_provider] = lambda: provider

    first = client.post(f"/selections/{selection.id}/generations")
    second = client.post(f"/selections/{selection.id}/generations")
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert db.query(QAGeneration).count() == 2
    assert len(store.documents) == 2
