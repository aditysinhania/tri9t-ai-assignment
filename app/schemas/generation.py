from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class QATestCaseResponse(BaseModel):
    title: str
    steps: list[str]
    expected_result: str
    source_section_paths: list[str] = Field(default_factory=list)


class SourceNodeSnapshot(BaseModel):
    node_id: int
    section_path: str | None
    heading: str
    content_hash: str
    position: int


class GenerationResponse(BaseModel):
    id: int
    selection_id: int
    mongo_id: str
    test_case_count: int
    created_at: datetime
    attempts_used: int
    source_nodes: list[SourceNodeSnapshot]
    test_cases: list[QATestCaseResponse]
