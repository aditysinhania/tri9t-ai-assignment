"""Unit tests for the CT-200 PDF parser (Phase 2B).

These target the irregular structures called out in the assignment:
missing intermediate headings, out-of-order sections, and duplicate titles.
"""

from __future__ import annotations

from app.parsers import ParsedNode
from app.parsers.pdf_parser import compute_content_hash


EXPECTED_V1_PATHS = [
    "1",
    "1.1",
    "1.2",
    "2",
    "2.1",
    "2.1.1.1",
    "2.2",
    "3",
    "3.1",
    "3.2",
    "3.4",
    "3.3",
    "4",
    "4.1",
    "4.2",
    "4.3",
    "5",
    "5.1",
    "5.2",
    "6",
    "6.1",
    "6.2",
    "7",
    "7.1",
    "7.2",
    "8",
    "8.1",
]


def nodes_by_path(tree: ParsedNode) -> dict[str, ParsedNode]:
    return {
        node.section_path: node
        for node in tree.iter_preorder()
        if node.section_path is not None
    }


def parent_path(tree: ParsedNode, child_path: str) -> str | None:
    for node in tree.iter_preorder():
        for child in node.children:
            if child.section_path == child_path:
                return node.section_path
    return None


def test_v1_contains_all_major_and_sub_sections(v1_tree):
    by_path = nodes_by_path(v1_tree)
    assert list(by_path.keys()) == EXPECTED_V1_PATHS
    assert [child.section_path for child in v1_tree.children] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
    ]


def test_heading_levels_match_section_depth(v1_tree):
    by_path = nodes_by_path(v1_tree)
    assert by_path["1"].level == 1
    assert by_path["1.1"].level == 2
    assert by_path["2.1"].level == 2
    assert by_path["2.1.1.1"].level == 4


def test_irregular_heading_2_1_1_1_attaches_to_2_1(v1_tree):
    """Missing intermediate 2.1.1 must not drop or mis-parent 2.1.1.1."""
    by_path = nodes_by_path(v1_tree)
    node = by_path["2.1.1.1"]

    assert "2.1.1" not in by_path
    assert node.heading == "Battery Life Under Typical Use"
    assert node.level == 4
    assert parent_path(v1_tree, "2.1.1.1") == "2.1"
    assert node in by_path["2.1"].children


def test_section_3_preserves_pdf_order_not_numeric_order(v1_tree):
    """3.4 appears before 3.3 in the PDF and must stay in that order."""
    section_3 = nodes_by_path(v1_tree)["3"]
    child_paths = [child.section_path for child in section_3.children]

    assert child_paths == ["3.1", "3.2", "3.4", "3.3"]
    assert child_paths != sorted(
        child_paths, key=lambda path: [int(part) for part in path.split(".")]
    )


def test_duplicate_error_codes_headings_are_distinct_nodes(v1_tree):
    """Same heading text under different parents must yield two node identities."""
    by_path = nodes_by_path(v1_tree)
    error_nodes = [
        node for node in v1_tree.iter_preorder() if node.heading == "Error Codes"
    ]

    assert len(error_nodes) == 2
    assert {node.section_path for node in error_nodes} == {"4.2", "7.1"}
    assert parent_path(v1_tree, "4.2") == "4"
    assert parent_path(v1_tree, "7.1") == "7"
    assert by_path["4.2"].content_hash != by_path["7.1"].content_hash
    assert id(by_path["4.2"]) != id(by_path["7.1"])


def test_tables_and_lists_are_preserved_in_node_bodies(v1_tree):
    by_path = nodes_by_path(v1_tree)

    specs = by_path["2.1"].body
    assert "Parameter Value" in specs
    assert "Measurement method" in specs
    assert "Oscillometric" in specs
    assert "Backlit LCD" in specs

    errors = by_path["4.2"].body
    assert "Code Meaning Device Behavior" in errors
    assert "E1" in errors and "E5" in errors

    classification = by_path["3.3"].body
    assert "1. Normal:" in classification
    assert "5. Hypertensive Crisis:" in classification
    assert "immediate medical attention" in classification


def test_no_duplicate_section_paths(v1_tree):
    paths = [
        node.section_path
        for node in v1_tree.iter_preorder()
        if node.section_path is not None
    ]
    assert len(paths) == len(set(paths))


def test_content_hash_is_stable_and_sensitive_to_edits():
    first = compute_content_hash("1.1", "Intended Use", "Hello world")
    second = compute_content_hash("1.1", "Intended Use", "Hello world")
    edited = compute_content_hash("1.1", "Intended Use", "Hello worle")

    assert first == second
    assert first != edited
    assert len(first) == 64


def test_v2_adds_data_export_section(v2_tree):
    by_path = nodes_by_path(v2_tree)
    assert "5.3" in by_path
    assert by_path["5.3"].heading == "Data Export"
    assert parent_path(v2_tree, "5.3") == "5"
    assert [child.section_path for child in by_path["5"].children] == [
        "5.1",
        "5.2",
        "5.3",
    ]
