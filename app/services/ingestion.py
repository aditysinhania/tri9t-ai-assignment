from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion, Node
from app.parsers import ParsedNode, parse_pdf


def persist_parsed_tree(
    db: Session,
    *,
    tree: ParsedNode,
    document_title: str,
    version_label: str,
    source_filename: str,
) -> DocumentVersion:
    """
    Persist an in-memory parsed tree as a new document version.

    Creates the Document row when needed (matched by title). Does not delete or
    overwrite prior versions of the same document.
    """
    document = db.query(Document).filter(Document.title == document_title).one_or_none()
    if document is None:
        document = Document(title=document_title)
        db.add(document)
        db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_label=version_label,
        source_filename=source_filename,
    )
    db.add(version)
    db.flush()

    _persist_node(db, tree, version_id=version.id, parent_id=None, position=0)
    db.commit()
    db.refresh(version)
    return version


def ingest_pdf(
    db: Session,
    pdf_path: str | Path,
    *,
    version_label: str,
    document_title: str | None = None,
) -> DocumentVersion:
    """Parse a PDF and persist the resulting tree."""
    path = Path(pdf_path)
    tree = parse_pdf(path)
    title = document_title or tree.heading
    return persist_parsed_tree(
        db,
        tree=tree,
        document_title=title,
        version_label=version_label,
        source_filename=path.name,
    )


def _persist_node(
    db: Session,
    parsed: ParsedNode,
    *,
    version_id: int,
    parent_id: int | None,
    position: int,
) -> Node:
    node = Node(
        version_id=version_id,
        parent_id=parent_id,
        heading=parsed.heading,
        level=parsed.level,
        body=parsed.body,
        section_path=parsed.section_path,
        content_hash=parsed.content_hash,
        position=position,
    )
    db.add(node)
    db.flush()

    for index, child in enumerate(parsed.children):
        _persist_node(
            db,
            child,
            version_id=version_id,
            parent_id=node.id,
            position=index,
        )
    return node
