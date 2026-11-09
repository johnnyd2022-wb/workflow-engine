"""Stable source identities keep mobile copy decisions attached to their text."""

from scripts.mobile_copy_inventory import CopyParser


def _parse(source: str) -> CopyParser:
    parser = CopyParser("example.html")
    parser.feed(source)
    return parser


def test_line_insertions_do_not_change_copy_or_container_keys() -> None:
    source = '<section class="card"><p>First point</p><p>Second point</p></section>'
    before = _parse(source)
    after = _parse("\n" * 12 + source)

    assert [(row["node_key"], row["container_key"]) for row in before.rows] == [
        (row["node_key"], row["container_key"]) for row in after.rows
    ]
    assert [row["source_line"] for row in before.rows] != [row["source_line"] for row in after.rows]


def test_changed_copy_gets_a_new_identity() -> None:
    before = _parse("<section><p>Original guidance</p></section>")
    after = _parse("<section><p>Revised guidance</p></section>")

    assert before.rows[0]["container_key"] == after.rows[0]["container_key"]
    assert before.rows[0]["node_key"] != after.rows[0]["node_key"]
