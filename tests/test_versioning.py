"""Version comparison tests using CT-200 V1 and V2 manuals."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Document, Selection
from app.services.ingestion import ingest_pdf
from app.services.versioning import compare_versions

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"
V2_PDF = PROJECT_ROOT / "data" / "ct200_manual_v2.pdf"


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


@pytest.fixture()
def v1_v2_versions(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    v2 = ingest_pdf(db_session, V2_PDF, version_label="v2")
    return v1, v2


def test_compare_detects_known_v1_v2_deltas(v1_v2_versions, db_session: Session):
    v1, v2 = v1_v2_versions
    comparison = compare_versions(db_session, v1.id, v2.id)

    modified_paths = {change.section_path for change in comparison.modified}
    added_paths = {change.section_path for change in comparison.added}
    removed_paths = {change.section_path for change in comparison.removed}
    unchanged_paths = {change.section_path for change in comparison.unchanged}

    # Known content edits in V2.
    assert {"2.1.1.1", "3.2", "4.2", "4.3"} <= modified_paths
    assert "5.3" in added_paths
    assert removed_paths == set()

    # Representative unchanged sections.
    assert {"1.1", "2.2", "3.1", "3.3", "3.4", "4.1", "5.1", "5.2", "6.1", "8.1"} <= (
        unchanged_paths
    )

    export = next(change for change in comparison.added if change.section_path == "5.3")
    assert export.heading_after == "Data Export"
    assert export.summary == "5.3 added"

    battery = next(
        change for change in comparison.modified if change.section_path == "2.1.1.1"
    )
    assert battery.hash_before != battery.hash_after
    assert "content hash changed" in battery.summary


def test_compare_is_symmetric_in_counts(v1_v2_versions, db_session: Session):
    v1, v2 = v1_v2_versions
    forward = compare_versions(db_session, v1.id, v2.id)
    reverse = compare_versions(db_session, v2.id, v1.id)

    assert len(forward.added) == len(reverse.removed)
    assert len(forward.removed) == len(reverse.added)
    assert len(forward.modified) == len(reverse.modified)
    assert len(forward.unchanged) == len(reverse.unchanged)


def test_compare_missing_version_raises(db_session: Session):
    v1 = ingest_pdf(db_session, V1_PDF, version_label="v1")
    with pytest.raises(ValueError, match="Compare version not found"):
        compare_versions(db_session, v1.id, 99999)
