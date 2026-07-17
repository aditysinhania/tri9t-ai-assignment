"""
End-to-end demo: V1 ingest → selection → QA generation → V2 ingest → staleness.

Runs in-process (no live server / Gemini / Mongo required). Uses a scripted
LLM and in-memory generation store so the versioning + staleness flow is
deterministic for reviewers.

Usage (from project root, with venv active):

    python scripts/e2e_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.api.generation import get_llm_provider
from app.core.database import Base, get_db
from app.db.mongo import InMemoryGenerationStore, get_generation_store
from app.llm.provider import ScriptedLLMProvider
from app.main import app
from app.models import Document, Node, QAGeneration, SelectionNode

V1_PDF = "data/ct200_manual.pdf"
V2_PDF = "data/ct200_manual_v2.pdf"

VALID_QA = {
    "test_cases": [
        {
            "title": "Battery low-icon threshold",
            "steps": ["Run until low-battery icon appears"],
            "expected_result": "Icon appears below the documented capacity threshold",
            "source_section_paths": ["2.1.1.1"],
        },
        {
            "title": "Intended use arm circumference",
            "steps": ["Confirm cuff fit for adult arm range"],
            "expected_result": "Device is used only within 22–42 cm arm circumference",
            "source_section_paths": ["1.1"],
        },
        {
            "title": "Error code E3 deflation",
            "steps": ["Simulate overpressure condition"],
            "expected_result": "Device displays E3 and auto-deflates",
            "source_section_paths": ["4.2"],
        },
    ]
}


def _node_id(db, version_id: int, section_path: str) -> int:
    node = (
        db.query(Node)
        .filter(Node.version_id == version_id, Node.section_path == section_path)
        .one_or_none()
    )
    if node is None:
        raise RuntimeError(f"Section {section_path} not found in version {version_id}")
    return node.id


def main() -> int:
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

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_generation_store] = lambda: store
    # Two generations (stale path + up-to-date path).
    app.dependency_overrides[get_llm_provider] = lambda: ScriptedLLMProvider(
        [json.dumps(VALID_QA), json.dumps(VALID_QA)]
    )

    client = TestClient(app)
    db = SessionLocal()
    print("=== CT-200 E2E: versioning + staleness ===\n")

    try:
        print("1) Ingest V1")
        v1 = client.post(
            "/documents/ingest",
            json={"pdf_path": V1_PDF, "version_label": "v1"},
        )
        v1.raise_for_status()
        v1_body = v1.json()
        print(
            f"   document_id={v1_body['document_id']} "
            f"version_id={v1_body['version_id']} nodes={v1_body['node_count']}"
        )

        battery_v1 = _node_id(db, v1_body["version_id"], "2.1.1.1")
        intended_v1 = _node_id(db, v1_body["version_id"], "1.1")

        print("2) Create selections (version-pinned to V1)")
        stale_sel = client.post(
            "/selections",
            json={
                "name": "Battery section (will go stale)",
                "version_id": v1_body["version_id"],
                "node_ids": [battery_v1],
            },
        )
        stale_sel.raise_for_status()
        fresh_sel = client.post(
            "/selections",
            json={
                "name": "Intended use (should stay up-to-date)",
                "version_id": v1_body["version_id"],
                "node_ids": [intended_v1],
            },
        )
        fresh_sel.raise_for_status()
        print(f"   stale_selection_id={stale_sel.json()['id']}")
        print(f"   fresh_selection_id={fresh_sel.json()['id']}")

        print("3) Generate QA for both selections")
        stale_gen = client.post(f"/selections/{stale_sel.json()['id']}/generations")
        stale_gen.raise_for_status()
        fresh_gen = client.post(f"/selections/{fresh_sel.json()['id']}/generations")
        fresh_gen.raise_for_status()
        print(f"   stale_generation_id={stale_gen.json()['id']}")
        print(f"   fresh_generation_id={fresh_gen.json()['id']}")

        print("4) Ingest V2 (does not overwrite V1)")
        v2 = client.post(
            "/documents/ingest",
            json={"pdf_path": V2_PDF, "version_label": "v2"},
        )
        v2.raise_for_status()
        v2_body = v2.json()
        print(
            f"   document_id={v2_body['document_id']} "
            f"version_id={v2_body['version_id']} nodes={v2_body['node_count']}"
        )
        assert v2_body["document_id"] == v1_body["document_id"]
        assert v2_body["version_id"] != v1_body["version_id"]

        print("5) Retrieve generations vs V2 (staleness)")
        stale_view = client.get(
            f"/generations/{stale_gen.json()['id']}",
            params={"target_version_id": v2_body["version_id"]},
        )
        stale_view.raise_for_status()
        fresh_view = client.get(
            f"/generations/{fresh_gen.json()['id']}",
            params={"target_version_id": v2_body["version_id"]},
        )
        fresh_view.raise_for_status()

        stale_status = stale_view.json()["staleness_status"]
        fresh_status = fresh_view.json()["staleness_status"]
        print(f"   battery generation status : {stale_status}")
        print(f"   intended-use generation   : {fresh_status}")

        print("6) Node-level change summary for 2.1.1.1")
        change = client.get(
            f"/nodes/{battery_v1}/changes",
            params={"other_version_id": v2_body["version_id"]},
        )
        change.raise_for_status()
        print(f"   {change.json()['summary']} (status={change.json()['status']})")

        ok = stale_status == "stale" and fresh_status == "up_to_date"
        print()
        if ok:
            print("PASS: V1 preserved, V2 ingested, staleness detected correctly.")
            return 0

        print("FAIL: unexpected staleness outcomes.")
        print(json.dumps(stale_view.json(), indent=2, default=str))
        print(json.dumps(fresh_view.json(), indent=2, default=str))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        app.dependency_overrides.clear()
