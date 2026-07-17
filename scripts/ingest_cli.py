"""
CLI helper to ingest a CT-200 PDF version into SQLite.

Usage (from project root):

    python scripts/ingest_cli.py data/ct200_manual.pdf --version-label v1
    python scripts/ingest_cli.py data/ct200_manual_v2.pdf --version-label v2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal, init_db
from app.models import Node
from app.services.ingestion import ingest_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a CT-200 manual PDF")
    parser.add_argument("pdf_path", help="Path to PDF (relative or absolute)")
    parser.add_argument(
        "--version-label",
        required=True,
        help="Version label, e.g. v1 or v2",
    )
    parser.add_argument(
        "--document-title",
        default=None,
        help="Optional document title override",
    )
    args = parser.parse_args()

    path = Path(args.pdf_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        print(f"ERROR: PDF not found: {path}", file=sys.stderr)
        return 1

    init_db()
    db = SessionLocal()
    try:
        version = ingest_pdf(
            db,
            path,
            version_label=args.version_label,
            document_title=args.document_title,
        )
        node_count = db.query(Node).filter(Node.version_id == version.id).count()
        print(
            f"Ingested {path.name} as version_label={version.version_label}\n"
            f"  document_id={version.document_id}\n"
            f"  version_id={version.id}\n"
            f"  node_count={node_count}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
