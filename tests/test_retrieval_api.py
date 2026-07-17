"""Retrieval API tests — fetch generations with staleness status."""

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
from app.llm.provider import ScriptedLLMProvider
from app.main import app
from app.models import Document, Node, QAGeneration, SelectionNode
from app.services.ingestion import ingest_pdf
from app.services.selections import create_selection

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
        yield client, db, store
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)


def _node_id(db, version_id: int, section_path: str) -> int:
    return (
        db.query(Node)
        .filter(Node.version_id == version_id, Node.section_path == section_path)
        .one()
        .id
    )


def _seed_v1_generation(client, db, paths: list[str]):
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    selection = create_selection(
        db,
        name="Retrieval probe",
        version_id=v1.id,
        node_ids=[_node_id(db, v1.id, path) for path in paths],
    )
    provider = ScriptedLLMProvider([json.dumps(VALID_PAYLOAD)])
    app.dependency_overrides[get_llm_provider] = lambda: provider
    created = client.post(f"/selections/{selection.id}/generations")
    assert created.status_code == 201
    return v1, selection, created.json()


def test_get_generation_includes_test_cases_and_staleness(client_ctx):
    client, db, _ = client_ctx
    v1, selection, created = _seed_v1_generation(client, db, ["2.1.1.1"])
    v2 = ingest_pdf(db, V2_PDF, version_label="v2")

    response = client.get(
        f"/generations/{created['id']}",
        params={"target_version_id": v2.id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["selection_id"] == selection.id
    assert len(body["test_cases"]) == 3
    assert body["staleness_status"] == "stale"
    assert body["node_staleness"][0]["section_path"] == "2.1.1.1"
    assert "wording change" in body["staleness_limitations"]


def test_list_generations_by_selection_shows_status(client_ctx):
    client, db, _ = client_ctx
    _, selection, created = _seed_v1_generation(client, db, ["1.1"])
    ingest_pdf(db, V2_PDF, version_label="v2")

    response = client.get(f"/selections/{selection.id}/generations")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == created["id"]
    assert items[0]["staleness_status"] == "up_to_date"


def test_list_generations_by_node_id(client_ctx):
    client, db, _ = client_ctx
    v1, _, created = _seed_v1_generation(client, db, ["1.1", "2.1.1.1"])
    battery_node = _node_id(db, v1.id, "2.1.1.1")
    intended_node = _node_id(db, v1.id, "1.1")
    ingest_pdf(db, V2_PDF, version_label="v2")

    battery = client.get(f"/nodes/{battery_node}/generations")
    intended = client.get(f"/nodes/{intended_node}/generations")

    assert battery.status_code == 200
    assert intended.status_code == 200
    assert len(battery.json()) == 1
    assert len(intended.json()) == 1
    assert battery.json()[0]["id"] == created["id"]
    # Overall generation is stale because 2.1.1.1 changed, even when queried via 1.1.
    assert battery.json()[0]["staleness_status"] == "stale"
    assert intended.json()[0]["staleness_status"] == "stale"

    detail = client.get(f"/generations/{created['id']}")
    by_path = {item["section_path"]: item["status"] for item in detail.json()["node_staleness"]}
    assert by_path["1.1"] == "up_to_date"
    assert by_path["2.1.1.1"] == "stale_modified"
