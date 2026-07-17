"""Selection API tests — version-pinned multi-node selections."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Document, Node, Selection, SelectionNode
from app.services.ingestion import ingest_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"
V2_PDF = PROJECT_ROOT / "data" / "ct200_manual_v2.pdf"


@pytest.fixture()
def client_and_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    assert Document.__tablename__
    assert SelectionNode.__tablename__
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    db = SessionLocal()
    try:
        yield client, db
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


def test_create_and_get_version_pinned_selection(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    node_ids = [
        _node_id(db, v1.id, "4.2"),
        _node_id(db, v1.id, "4.1"),
    ]

    create = client.post(
        "/selections",
        json={
            "name": "Overpressure QA",
            "version_id": v1.id,
            "node_ids": node_ids,
        },
    )
    assert create.status_code == 201
    payload = create.json()
    assert payload["name"] == "Overpressure QA"
    assert payload["version_id"] == v1.id
    assert [item["section_path"] for item in payload["nodes"]] == ["4.2", "4.1"]
    assert payload["nodes"][0]["content_hash"]

    fetched = client.get(f"/selections/{payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]
    assert len(fetched.json()["nodes"]) == 2


def test_selection_rejects_nodes_from_another_version(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db, V2_PDF, version_label="v2")
    v2_node = _node_id(db, v2.id, "1.1")

    response = client.post(
        "/selections",
        json={
            "name": "Bad mix",
            "version_id": v1.id,
            "node_ids": [v2_node],
        },
    )
    assert response.status_code == 400
    assert "pinned version_id" in response.json()["detail"]


def test_selection_survives_newer_version_ingest(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    battery_v1 = _node_id(db, v1.id, "2.1.1.1")
    created = client.post(
        "/selections",
        json={
            "name": "Battery checks",
            "version_id": v1.id,
            "node_ids": [battery_v1],
        },
    )
    selection_id = created.json()["id"]
    original_hash = created.json()["nodes"][0]["content_hash"]

    ingest_pdf(db, V2_PDF, version_label="v2")

    fetched = client.get(f"/selections/{selection_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["version_id"] == v1.id
    assert body["nodes"][0]["node_id"] == battery_v1
    assert body["nodes"][0]["content_hash"] == original_hash

    # V1 selection rows remain distinct from any V2 nodes.
    assert db.query(Selection).filter(Selection.id == selection_id).one().version_id == (
        v1.id
    )


def test_list_selections_can_filter_by_version(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db, V2_PDF, version_label="v2")

    client.post(
        "/selections",
        json={
            "name": "V1 only",
            "version_id": v1.id,
            "node_ids": [_node_id(db, v1.id, "1.1")],
        },
    )
    client.post(
        "/selections",
        json={
            "name": "V2 only",
            "version_id": v2.id,
            "node_ids": [_node_id(db, v2.id, "5.3")],
        },
    )

    all_selections = client.get("/selections")
    assert all_selections.status_code == 200
    assert len(all_selections.json()) == 2

    filtered = client.get("/selections", params={"version_id": v1.id})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["name"] == "V1 only"
