"""Persistence tests: parsed PDF tree is stored with hierarchy and hashes."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Document, DocumentVersion, Node, Selection
from app.services.ingestion import ingest_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Register model metadata before create_all.
    assert Document.__tablename__
    assert Selection.__tablename__
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_ingest_persists_full_hierarchy_and_hashes(db_session: Session):
    version = ingest_pdf(db_session, V1_PDF, version_label="v1")

    assert version.version_label == "v1"
    assert version.source_filename == "ct200_manual.pdf"

    nodes = (
        db_session.query(Node)
        .filter(Node.version_id == version.id)
        .order_by(Node.id)
        .all()
    )
    # Root title + 27 numbered sections.
    assert len(nodes) == 28

    by_path = {node.section_path: node for node in nodes if node.section_path}
    assert by_path["2.1.1.1"].parent_id == by_path["2.1"].id
    assert by_path["2.1.1.1"].level == 4
    assert by_path["2.1.1.1"].content_hash

    section_3 = by_path["3"]
    children = (
        db_session.query(Node)
        .filter(Node.parent_id == section_3.id)
        .order_by(Node.position)
        .all()
    )
    assert [child.section_path for child in children] == ["3.1", "3.2", "3.4", "3.3"]

    error_nodes = [node for node in nodes if node.heading == "Error Codes"]
    assert len(error_nodes) == 2
    assert {node.section_path for node in error_nodes} == {"4.2", "7.1"}


def test_reingest_creates_second_version_without_overwrite(db_session: Session):
    first = ingest_pdf(db_session, V1_PDF, version_label="v1")
    second = ingest_pdf(db_session, V1_PDF, version_label="v2")

    versions = db_session.query(DocumentVersion).all()
    assert len(versions) == 2
    assert {version.version_label for version in versions} == {"v1", "v2"}

    docs = db_session.query(Document).all()
    assert len(docs) == 1

    v1_count = db_session.query(Node).filter(Node.version_id == first.id).count()
    v2_count = db_session.query(Node).filter(Node.version_id == second.id).count()
    assert v1_count == 28
    assert v2_count == 28
