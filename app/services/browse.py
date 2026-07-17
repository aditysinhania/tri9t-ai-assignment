from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, Node
from app.services.versioning import ROOT_KEY, NodeChange, compare_versions


def get_latest_version(db: Session, document_id: int) -> DocumentVersion | None:
    return (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.ingested_at.desc(), DocumentVersion.id.desc())
        .first()
    )


def resolve_version(
    db: Session, document_id: int, version_id: int | None
) -> DocumentVersion:
    document = db.get(Document, document_id)
    if document is None:
        raise LookupError(f"Document not found: {document_id}")

    if version_id is None:
        version = get_latest_version(db, document_id)
        if version is None:
            raise LookupError(f"No versions found for document {document_id}")
        return version

    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise LookupError(
            f"Version {version_id} not found for document {document_id}"
        )
    return version


def list_top_level_sections(db: Session, version_id: int) -> list[Node]:
    root = (
        db.query(Node)
        .filter(Node.version_id == version_id, Node.parent_id.is_(None))
        .one_or_none()
    )
    if root is None:
        return []
    return (
        db.query(Node)
        .filter(Node.parent_id == root.id)
        .order_by(Node.position.asc(), Node.id.asc())
        .all()
    )


def get_node(db: Session, node_id: int) -> Node | None:
    return db.get(Node, node_id)


def get_child_summaries(db: Session, node_id: int) -> list[Node]:
    return (
        db.query(Node)
        .filter(Node.parent_id == node_id)
        .order_by(Node.position.asc(), Node.id.asc())
        .all()
    )


def search_nodes(db: Session, version_id: int, query: str) -> list[Node]:
    pattern = f"%{query.strip()}%"
    return (
        db.query(Node)
        .filter(
            Node.version_id == version_id,
            or_(Node.heading.ilike(pattern), Node.body.ilike(pattern)),
        )
        .order_by(Node.level.asc(), Node.position.asc(), Node.id.asc())
        .all()
    )


def _latest_other_version(
    db: Session, node: Node, other_version_id: int | None
) -> DocumentVersion:
    version = db.get(DocumentVersion, node.version_id)
    if version is None:
        raise LookupError(f"Version not found for node {node.id}")

    if other_version_id is not None:
        other = db.get(DocumentVersion, other_version_id)
        if other is None or other.document_id != version.document_id:
            raise LookupError(
                f"Version {other_version_id} not found for this document"
            )
        if other.id == version.id:
            raise ValueError("other_version_id must differ from the node's version")
        return other

    other = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.id != version.id,
        )
        .order_by(DocumentVersion.ingested_at.desc(), DocumentVersion.id.desc())
        .first()
    )
    if other is None:
        raise LookupError("No other version available to compare against")
    return other


def compare_node_across_versions(
    db: Session, node_id: int, other_version_id: int | None = None
) -> tuple[NodeChange, int, int]:
    """
    Compare one node to the matching logical node in another version.

    Returns (change, base_version_id, compare_version_id) where base is the
    node's version and compare is the other version.
    """
    node = db.get(Node, node_id)
    if node is None:
        raise LookupError(f"Node not found: {node_id}")

    other_version = _latest_other_version(db, node, other_version_id)
    comparison = compare_versions(db, node.version_id, other_version.id)
    key = node.section_path if node.section_path is not None else ROOT_KEY

    for change in comparison.changes:
        change_key = (
            ROOT_KEY if change.section_path is None else change.section_path
        )
        if change_key == key:
            return change, node.version_id, other_version.id

    raise LookupError(f"No comparison entry found for node {node_id}")
