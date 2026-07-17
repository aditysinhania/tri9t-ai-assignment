from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.generation import QATestCaseResponse, SourceNodeSnapshot
from app.schemas.staleness import NodeStalenessDetail


class GenerationSummary(BaseModel):
    id: int
    selection_id: int
    mongo_id: str
    test_case_count: int
    created_at: datetime
    staleness_status: str
    source_version_id: int
    target_version_id: int


class GenerationRetrievalResponse(BaseModel):
    id: int
    selection_id: int
    mongo_id: str
    test_case_count: int
    created_at: datetime
    attempts_used: int
    source_nodes: list[SourceNodeSnapshot]
    test_cases: list[QATestCaseResponse]
    staleness_status: str
    source_version_id: int
    target_version_id: int
    node_staleness: list[NodeStalenessDetail]
    staleness_limitations: str
