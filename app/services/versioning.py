from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from app.models import DocumentVersion, Node

ChangeStatus = Literal["unchanged", "modified", "added", "removed"]

ROOT_KEY = "__root__"


@dataclass
class NodeChange:
    """Lightweight per-node diff between two document versions."""

    section_path: str | None
    status: ChangeStatus
    base_node_id: int | None
    compare_node_id: int | None
    heading_before: str | None
    heading_after: str | None
    hash_before: str | None
    hash_after: str | None
    summary: str


@dataclass
class VersionComparison:
    base_version_id: int
    compare_version_id: int
    unchanged: list[NodeChange] = field(default_factory=list)
    modified: list[NodeChange] = field(default_factory=list)
    added: list[NodeChange] = field(default_factory=list)
    removed: list[NodeChange] = field(default_factory=list)

    @property
    def changes(self) -> list[NodeChange]:
        return self.unchanged + self.modified + self.added + self.removed


def _logical_key(node: Node) -> str:
    return node.section_path if node.section_path is not None else ROOT_KEY


def _index_nodes(nodes: list[Node]) -> dict[str, Node]:
    indexed: dict[str, Node] = {}
    for node in nodes:
        key = _logical_key(node)
        if key in indexed:
            raise ValueError(
                f"Duplicate logical key {key!r} within version {node.version_id}"
            )
        indexed[key] = node
    return indexed


def _display_path(key: str) -> str:
    return "ROOT" if key == ROOT_KEY else key


def compare_versions(
    db: Session,
    base_version_id: int,
    compare_version_id: int,
) -> VersionComparison:
    """
    Compare two persisted versions using section_path identity + content hashes.

    Known failure modes:
    - Renumbered sections appear as removed + added, not renamed.
    - A reused section_path with different meaning is reported as modified.
    """
    base_version = db.get(DocumentVersion, base_version_id)
    compare_version = db.get(DocumentVersion, compare_version_id)
    if base_version is None:
        raise ValueError(f"Base version not found: {base_version_id}")
    if compare_version is None:
        raise ValueError(f"Compare version not found: {compare_version_id}")

    base_nodes = db.query(Node).filter(Node.version_id == base_version_id).all()
    compare_nodes = db.query(Node).filter(Node.version_id == compare_version_id).all()

    base_index = _index_nodes(base_nodes)
    compare_index = _index_nodes(compare_nodes)

    result = VersionComparison(
        base_version_id=base_version_id,
        compare_version_id=compare_version_id,
    )

    all_keys = sorted(
        set(base_index) | set(compare_index),
        key=lambda key: (key == ROOT_KEY, key),
    )

    for key in all_keys:
        base_node = base_index.get(key)
        compare_node = compare_index.get(key)
        path = None if key == ROOT_KEY else key
        label = _display_path(key)

        if base_node is not None and compare_node is not None:
            if base_node.content_hash == compare_node.content_hash:
                change = NodeChange(
                    section_path=path,
                    status="unchanged",
                    base_node_id=base_node.id,
                    compare_node_id=compare_node.id,
                    heading_before=base_node.heading,
                    heading_after=compare_node.heading,
                    hash_before=base_node.content_hash,
                    hash_after=compare_node.content_hash,
                    summary=f"{label} unchanged",
                )
                result.unchanged.append(change)
            else:
                heading_note = ""
                if base_node.heading != compare_node.heading:
                    heading_note = " (heading text also changed)"
                change = NodeChange(
                    section_path=path,
                    status="modified",
                    base_node_id=base_node.id,
                    compare_node_id=compare_node.id,
                    heading_before=base_node.heading,
                    heading_after=compare_node.heading,
                    hash_before=base_node.content_hash,
                    hash_after=compare_node.content_hash,
                    summary=f"{label} content hash changed{heading_note}",
                )
                result.modified.append(change)
        elif compare_node is not None:
            change = NodeChange(
                section_path=path,
                status="added",
                base_node_id=None,
                compare_node_id=compare_node.id,
                heading_before=None,
                heading_after=compare_node.heading,
                hash_before=None,
                hash_after=compare_node.content_hash,
                summary=f"{label} added",
            )
            result.added.append(change)
        else:
            assert base_node is not None
            change = NodeChange(
                section_path=path,
                status="removed",
                base_node_id=base_node.id,
                compare_node_id=None,
                heading_before=base_node.heading,
                heading_after=None,
                hash_before=base_node.content_hash,
                hash_after=None,
                summary=f"{label} removed",
            )
            result.removed.append(change)

    return result
