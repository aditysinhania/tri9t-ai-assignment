from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SelectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version_id: int
    node_ids: list[int] = Field(min_length=1)


class SelectionNodeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    position: int
    heading: str
    section_path: str | None
    content_hash: str
    body: str


class SelectionResponse(BaseModel):
    id: int
    name: str
    version_id: int
    created_at: datetime
    nodes: list[SelectionNodeItem]
