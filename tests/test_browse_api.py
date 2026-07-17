"""Browse API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Document, Node, Selection
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
    assert Selection.__tablename__
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


def test_list_sections_defaults_to_latest(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db, V2_PDF, version_label="v2")
    document_id = v1.document_id

    response = client.get(f"/documents/{document_id}/sections")
    assert response.status_code == 200
    sections = response.json()
    assert [item["section_path"] for item in sections] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
    ]

    # Latest is v2; section 5 exists in both, but children differ — top-level still 8.
    pinned = client.get(
        f"/documents/{document_id}/sections", params={"version_id": v1.id}
    )
    assert pinned.status_code == 200
    assert len(pinned.json()) == 8
    assert v2.id != v1.id


def test_get_node_includes_children_body_and_hash(client_and_db):
    client, db = client_and_db
    version = ingest_pdf(db, V1_PDF, version_label="v1")
    section_3 = (
        db.query(Node)
        .filter(Node.version_id == version.id, Node.section_path == "3")
        .one()
    )

    response = client.get(f"/nodes/{section_3.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["section_path"] == "3"
    assert payload["content_hash"]
    assert [child["section_path"] for child in payload["children"]] == [
        "3.1",
        "3.2",
        "3.4",
        "3.3",
    ]


def test_search_nodes_by_heading_and_body(client_and_db):
    client, db = client_and_db
    version = ingest_pdf(db, V1_PDF, version_label="v1")

    response = client.get(
        f"/versions/{version.id}/nodes/search", params={"q": "Error Codes"}
    )
    assert response.status_code == 200
    results = response.json()
    assert {item["section_path"] for item in results} == {"4.2", "7.1"}

    cuff = client.get(
        f"/versions/{version.id}/nodes/search", params={"q": "Oscillometric"}
    )
    assert cuff.status_code == 200
    assert any(item["section_path"] == "2.1" for item in cuff.json())


def test_node_changes_reports_modified_and_unchanged(client_and_db):
    client, db = client_and_db
    v1 = ingest_pdf(db, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db, V2_PDF, version_label="v2")

    battery_v1 = (
        db.query(Node)
        .filter(Node.version_id == v1.id, Node.section_path == "2.1.1.1")
        .one()
    )
    intended_v1 = (
        db.query(Node)
        .filter(Node.version_id == v1.id, Node.section_path == "1.1")
        .one()
    )

    modified = client.get(
        f"/nodes/{battery_v1.id}/changes",
        params={"other_version_id": v2.id},
    )
    assert modified.status_code == 200
    modified_payload = modified.json()
    assert modified_payload["status"] == "modified"
    assert modified_payload["section_path"] == "2.1.1.1"
    assert modified_payload["hash_before"] != modified_payload["hash_after"]

    unchanged = client.get(
        f"/nodes/{intended_v1.id}/changes",
        params={"other_version_id": v2.id},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["status"] == "unchanged"
