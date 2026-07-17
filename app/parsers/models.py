from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedNode:
    """In-memory document node produced by the PDF parser."""

    heading: str
    level: int
    body: str
    section_path: str | None
    content_hash: str = ""
    children: list[ParsedNode] = field(default_factory=list)

    def iter_preorder(self) -> list[ParsedNode]:
        """Return this node and all descendants in document order."""
        nodes = [self]
        for child in self.children:
            nodes.extend(child.iter_preorder())
        return nodes
