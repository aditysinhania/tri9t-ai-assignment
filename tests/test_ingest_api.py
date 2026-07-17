"""Ingest API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import Document, DocumentVersion, Node, Selection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = "data/ct200_manual.pdf"
V2_PDF = "data/ct200_manual_v2.pdf"


@pytest.fixture()
def client():
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
    test_client = TestClient(app)
    try:
        yield test_client, SessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)


def test_ingest_v1_and_v2_without_overwrite(client):
    test_client, SessionLocal = client

    v1 = test_client.post(
        "/documents/ingest",
        json={"pdf_path": V1_PDF, "version_label": "v1"},
    )
    assert v1.status_code == 201
    v1_body = v1.json()
    assert v1_body["version_label"] == "v1"
    assert v1_body["node_count"] == 28
    assert v1_body["source_filename"] == "ct200_manual.pdf"

    v2 = test_client.post(
        "/documents/ingest",
        json={"pdf_path": V2_PDF, "version_label": "v2"},
    )
    assert v2.status_code == 201
    v2_body = v2.json()
    assert v2_body["document_id"] == v1_body["document_id"]
    assert v2_body["version_id"] != v1_body["version_id"]
    assert v2_body["node_count"] == 29

    db = SessionLocal()
    try:
        assert db.query(Document).count() == 1
        assert db.query(DocumentVersion).count() == 2
        v1_nodes = (
            db.query(Node)
            .filter(Node.version_id == v1_body["version_id"])
            .count()
        )
        assert v1_nodes == 28
    finally:
        db.close()


def test_ingest_missing_pdf_returns_404(client):
    test_client, _ = client
    response = test_client.post(
        "/documents/ingest",
        json={"pdf_path": "data/does_not_exist.pdf", "version_label": "v1"},
    )
    assert response.status_code == 404
