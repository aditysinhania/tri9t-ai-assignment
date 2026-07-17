from __future__ import annotations

from pathlib import Path

import pytest

from app.parsers import ParsedNode, parse_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PDF = PROJECT_ROOT / "data" / "ct200_manual.pdf"
V2_PDF = PROJECT_ROOT / "data" / "ct200_manual_v2.pdf"


@pytest.fixture(scope="module")
def v1_tree() -> ParsedNode:
    assert V1_PDF.is_file(), f"Missing fixture PDF: {V1_PDF}"
    return parse_pdf(V1_PDF)


@pytest.fixture(scope="module")
def v2_tree() -> ParsedNode:
    assert V2_PDF.is_file(), f"Missing fixture PDF: {V2_PDF}"
    return parse_pdf(V2_PDF)
