from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    nodes: Mapped[list[Node]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    selections: Mapped[list[Selection]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "section_path",
            name="uq_nodes_version_section_path",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    heading: Mapped[str] = mapped_column(String(512), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    section_path: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    version: Mapped[DocumentVersion] = relationship(back_populates="nodes")
    parent: Mapped[Node | None] = relationship(
        remote_side="Node.id", back_populates="children"
    )
    children: Mapped[list[Node]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    selection_links: Mapped[list[SelectionNode]] = relationship(
        back_populates="node"
    )


class Selection(Base):
    """Named selection pinned to a specific document version."""

    __tablename__ = "selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    version: Mapped[DocumentVersion] = relationship(back_populates="selections")
    node_links: Mapped[list[SelectionNode]] = relationship(
        back_populates="selection",
        cascade="all, delete-orphan",
        order_by="SelectionNode.position",
    )


class SelectionNode(Base):
    """Ordered membership of a version-specific node inside a selection."""

    __tablename__ = "selection_nodes"
    __table_args__ = (
        UniqueConstraint(
            "selection_id",
            "node_id",
            name="uq_selection_nodes_selection_node",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(
        ForeignKey("selections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    selection: Mapped[Selection] = relationship(back_populates="node_links")
    node: Mapped[Node] = relationship(back_populates="selection_links")
