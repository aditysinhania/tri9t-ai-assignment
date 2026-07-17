from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from app.parsers.models import ParsedNode

PAGE_MARKER_RE = re.compile(r"^--\s*\d+\s+of\s+\d+\s*--\s*$")
# Nested headings: "1.1 Title", "2.1.1.1 Title" (no trailing dot before the title).
NESTED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")
# Top-level headings: "1. Title" (required trailing dot after the single number).
TOP_LEVEL_HEADING_RE = re.compile(r"^(\d+)\.\s+(.+)$")
# In-body lists such as "1. Normal: ..." — must not become section nodes.
LIST_ITEM_RE = re.compile(r"^\d+\.\s+.+:")


def _normalize_whitespace(text: str) -> str:
    # NFKC folds PDF ligatures (e.g. ﬁ → fi) into plain ASCII-compatible forms.
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _normalize_for_hash(text: str) -> str:
    """Stable normalization so trivial whitespace differences do not change hashes."""
    lines = [_normalize_whitespace(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def compute_content_hash(section_path: str | None, heading: str, body: str) -> str:
    payload = f"{section_path or ''}\n{heading}\n{_normalize_for_hash(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract raw text from a PDF, preserving page order."""
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _clean_lines(raw_text: str) -> list[str]:
    """Split into lines and drop page markers / empty lines."""
    cleaned: list[str] = []
    for line in raw_text.splitlines():
        stripped = _normalize_whitespace(line)
        if not stripped:
            continue
        if PAGE_MARKER_RE.match(stripped):
            continue
        cleaned.append(stripped)
    return cleaned


def _level_from_path(section_path: str) -> int:
    return len(section_path.split("."))


def _is_prefix_path(parent_path: str, child_path: str) -> bool:
    """Return True if parent_path is a proper path-prefix of child_path."""
    parent_parts = parent_path.split(".")
    child_parts = child_path.split(".")
    if len(parent_parts) >= len(child_parts):
        return False
    return child_parts[: len(parent_parts)] == parent_parts


def _is_section_heading(line: str) -> re.Match[str] | None:
    """
    Match numbered section headings; exclude in-body numbered list items.

    Top-level manuals use "1. Title" while nested sections use "1.1 Title"
    (no extra trailing dot). Those forms must be handled separately.
    """
    if LIST_ITEM_RE.match(line):
        return None
    return NESTED_HEADING_RE.match(line) or TOP_LEVEL_HEADING_RE.match(line)


def build_tree_from_lines(lines: list[str]) -> ParsedNode:
    """
    Build a hierarchical tree from cleaned PDF lines.

    Document order is preserved. Missing intermediate paths (e.g. 2.1.1.1 under 2.1)
    attach to the deepest existing prefix parent.
    """
    if not lines:
        raise ValueError("PDF contained no extractable text")

    # Title: everything before the first numbered section heading.
    first_heading_idx = 0
    while first_heading_idx < len(lines) and not _is_section_heading(lines[first_heading_idx]):
        first_heading_idx += 1

    if first_heading_idx == 0:
        title = "Untitled Document"
        body_start = 0
    else:
        title = " ".join(lines[:first_heading_idx])
        body_start = first_heading_idx

    root = ParsedNode(heading=title, level=0, body="", section_path=None)

    # Stack holds (section_path, node) for open ancestors, root first.
    stack: list[tuple[str | None, ParsedNode]] = [(None, root)]
    current = root
    body_lines: list[str] = []

    def flush_body() -> None:
        nonlocal body_lines
        current.body = "\n".join(body_lines).strip()
        body_lines = []

    for line in lines[body_start:]:
        match = _is_section_heading(line)
        if match:
            flush_body()
            section_path, heading_text = match.group(1), match.group(2).strip()
            level = _level_from_path(section_path)
            node = ParsedNode(
                heading=heading_text,
                level=level,
                body="",
                section_path=section_path,
            )

            # Pop until the top of the stack is a valid parent prefix (or root).
            while len(stack) > 1:
                parent_path, _ = stack[-1]
                assert parent_path is not None
                if _is_prefix_path(parent_path, section_path):
                    break
                stack.pop()

            parent = stack[-1][1]
            parent.children.append(node)
            stack.append((section_path, node))
            current = node
            continue

        body_lines.append(line)

    flush_body()

    # Assign content hashes after bodies are complete (children not part of hash).
    for node in root.iter_preorder():
        node.content_hash = compute_content_hash(
            node.section_path, node.heading, node.body
        )

    return root


def parse_pdf(pdf_path: str | Path) -> ParsedNode:
    """Parse a CT-200 manual PDF into an in-memory hierarchical tree."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")

    raw_text = extract_pdf_text(path)
    lines = _clean_lines(raw_text)
    return build_tree_from_lines(lines)
