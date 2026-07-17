from __future__ import annotations

from pydantic import BaseModel


class NodeStalenessDetail(BaseModel):
    section_path: str | None
    heading: str | None
    status: str  # up_to_date | stale_modified | stale_removed
    hash_at_generation: str
    hash_in_target: str | None
    reason: str


class GenerationStaleness(BaseModel):
    generation_id: int
    selection_id: int
    source_version_id: int
    target_version_id: int
    status: str  # up_to_date | stale
    node_details: list[NodeStalenessDetail]
    limitations: str
