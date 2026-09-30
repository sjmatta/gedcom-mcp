"""Run this contract against any replacement GedcomEditor adapter."""

from pathlib import Path

import pytest

from gedcom_server.editing import default_editor
from gedcom_server.writes import TreeStore


@pytest.fixture
def editor():
    # Parametrize factories here when evaluating a library adapter.
    return default_editor()


@pytest.fixture
def raw():
    return (Path(__file__).parent / "fixtures" / "sample.ged").read_bytes()


@pytest.mark.parametrize("bom,newline", [(False, b"\n"), (True, b"\r\n")])
def test_backend_exact_record_chunks(editor, raw, bom, newline):
    data = raw.replace(b"\n", newline)
    if bom:
        data = b"\xef\xbb\xbf" + data
    editor.validate(data)
    assert b"".join(editor.records(data)) == data


def test_backend_preserves_unknown_structure_and_unicode(editor, raw):
    custom = "1 _UNKNOWN opaque\n2 _DETAIL exact\n1 NOTE Unicode\u2028separator\n".encode()
    raw = raw.replace(b"1 SEX M\n", b"1 SEX M\n" + custom, 1)
    result = editor.apply(raw, [{"op": "add_note", "record_id": "@I1@", "text": "new note"}])
    assert result.affected_records == ("@I1@",)
    assert result.data.replace(b"1 NOTE new note\n", b"", 1) == raw
    assert custom in result.data
    assert "+1 NOTE new note" in "\n".join(editor.diff(raw, result.data, ["@I1@"]))


def test_backend_failed_batch_leaves_input_unchanged(editor, raw):
    original = bytes(raw)
    with pytest.raises(ValueError):
        editor.apply(
            raw,
            [
                {"op": "add_note", "record_id": "@I1@", "text": "valid"},
                {"op": "add_note", "record_id": "@missing@", "text": "invalid"},
            ],
        )
    assert raw == original


def test_store_accepts_backend_without_parser_node_api(editor, raw, tmp_path):
    calls = []

    class AlternateBackend:
        def validate(self, data):
            calls.append("validate")
            return editor.validate(data)

        def records(self, data):
            calls.append("records")
            return editor.records(data)

        def apply(self, data, operations):
            calls.append("apply")
            return editor.apply(data, operations)

        def diff(self, before, after, affected):
            calls.append("diff")
            return editor.diff(before, after, affected)

    baseline = tmp_path / "baseline.ged"
    baseline.write_bytes(raw)
    tree = TreeStore(baseline, tmp_path / "store", editor=AlternateBackend())
    try:
        proposal = tree.prepare(
            0, "Adapter contract", [{"op": "add_note", "record_id": "@I1@", "text": "test"}]
        )
        assert "+1 NOTE test" in proposal["diff"]
        assert set(calls) == {"validate", "records", "apply", "diff"}
    finally:
        tree.close()
