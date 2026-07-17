from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import DocumentVersion, Node, Selection, SelectionNode


def create_selection(
    db: Session,
    *,
    name: str,
    version_id: int,
    node_ids: list[int],
) -> Selection:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise LookupError(f"Version not found: {version_id}")

    if not node_ids:
        raise ValueError("At least one node_id is required")

    # Preserve caller order; reject duplicates.
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("node_ids must be unique")

    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    nodes_by_id = {node.id: node for node in nodes}

    missing = [node_id for node_id in node_ids if node_id not in nodes_by_id]
    if missing:
        raise LookupError(f"Nodes not found: {missing}")

    wrong_version = [
        node_id
        for node_id in node_ids
        if nodes_by_id[node_id].version_id != version_id
    ]
    if wrong_version:
        raise ValueError(
            "All nodes must belong to the pinned version_id; "
            f"mismatched node_ids: {wrong_version}"
        )

    selection = Selection(name=name.strip(), version_id=version_id)
    db.add(selection)
    db.flush()

    for position, node_id in enumerate(node_ids):
        db.add(
            SelectionNode(
                selection_id=selection.id,
                node_id=node_id,
                position=position,
            )
        )

    db.commit()
    return get_selection(db, selection.id)


def get_selection(db: Session, selection_id: int) -> Selection:
    selection = (
        db.query(Selection)
        .options(
            joinedload(Selection.node_links).joinedload(SelectionNode.node),
        )
        .filter(Selection.id == selection_id)
        .one_or_none()
    )
    if selection is None:
        raise LookupError(f"Selection not found: {selection_id}")
    return selection


def list_selections(
    db: Session, *, version_id: int | None = None
) -> list[Selection]:
    query = db.query(Selection).options(
        joinedload(Selection.node_links).joinedload(SelectionNode.node),
    )
    if version_id is not None:
        version = db.get(DocumentVersion, version_id)
        if version is None:
            raise LookupError(f"Version not found: {version_id}")
        query = query.filter(Selection.version_id == version_id)
    return query.order_by(Selection.id.asc()).all()


def selection_to_payload(selection: Selection) -> dict:
    nodes = []
    for link in sorted(selection.node_links, key=lambda item: item.position):
        node = link.node
        nodes.append(
            {
                "node_id": node.id,
                "position": link.position,
                "heading": node.heading,
                "section_path": node.section_path,
                "content_hash": node.content_hash,
                "body": node.body,
            }
        )
    return {
        "id": selection.id,
        "name": selection.name,
        "version_id": selection.version_id,
        "created_at": selection.created_at,
        "nodes": nodes,
    }
