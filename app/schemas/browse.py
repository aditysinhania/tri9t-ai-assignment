from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NodeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    heading: str
    level: int
    section_path: str | None
    content_hash: str
    position: int
    parent_id: int | None


class NodeDetail(NodeSummary):
    body: str
    version_id: int
    children: list[NodeSummary] = []


class NodeSearchResult(NodeSummary):
    body_preview: str


class NodeChangeResponse(BaseModel):
    section_path: str | None
    status: str
    base_node_id: int | None
    compare_node_id: int | None
    heading_before: str | None
    heading_after: str | None
    hash_before: str | None
    hash_after: str | None
    summary: str
    base_version_id: int
    compare_version_id: int
