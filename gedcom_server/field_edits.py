"""Reviewed, lossless edits of arbitrary GEDCOM fields and auxiliary records."""

import hashlib
import re
from collections import Counter

TAG = re.compile(r"^[A-Za-z0-9_]{1,31}$")
XREF = re.compile(r"^@[^@\s]+@$")
OPERATIONS = {
    "add_field",
    "update_field",
    "replace_field",
    "remove_field",
    "add_record",
    "remove_record",
    "update_relationship",
}
MAX_TEXT_BYTES = 1024 * 1024


def tag_value(tag):
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ValueError("Tag must contain 1–31 letters, digits or underscores")
    return tag


def record_id_value(doc, record_id):
    doc.value(record_id)
    if not XREF.fullmatch(record_id):
        raise ValueError("New record_id must be a GEDCOM @ID@ cross-reference")
    if any(line.xref == record_id for line in doc.lines):
        raise ValueError("Record ID already exists")
    return record_id


def text_value(value):
    if not isinstance(value, str):
        raise ValueError("Text must be a string")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Text exceeds 1 MiB of UTF-8")
    if any((ord(c) < 32 and c not in "\r\n") or ord(c) == 127 for c in value):
        raise ValueError("Text contains unsupported control characters")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def chunks(value):
    """Split on UTF-8 boundaries without losing whitespace or punctuation."""
    encoded = value.encode("utf-8")
    offset = 0
    while len(encoded) - offset > 200:
        first = encoded[offset : offset + 200].decode("utf-8", errors="ignore")
        yield first
        offset += len(first.encode("utf-8"))
    yield encoded[offset:].decode("utf-8")


def text_lines(doc, level, tag, value="", xref=None):
    tag = tag_value(tag)
    value = text_value(value)
    result = []
    for line_index, paragraph in enumerate(value.split("\n")):
        for chunk_index, part in enumerate(chunks(paragraph)):
            if line_index == chunk_index == 0:
                prefix = f"{level} {xref + ' ' if xref else ''}{tag}"
            else:
                continuation = "CONT" if chunk_index == 0 else "CONC"
                prefix = f"{level + 1} {continuation}"
            result.append(prefix + (" " + part if part else "") + doc.newline)
    return "".join(result)


def render_node(doc, node, level):
    if level > 64:
        raise ValueError("New field nesting exceeds 64 levels")
    result = text_lines(doc, level, node["tag"], node.get("value", ""))
    for child in node.get("children", []):
        result += render_node(doc, child, level + 1)
    if len(result.encode("utf-8")) > 8 * MAX_TEXT_BYTES:
        raise ValueError("New subtree exceeds 8 MiB")
    return result


def children(doc, start):
    return [
        i
        for i in range(start + 1, doc.end(start))
        if doc.lines[i].level == doc.lines[start].level + 1
    ]


def subtree_hash(doc, start):
    return hashlib.sha256(
        "".join(line.raw for line in doc.lines[start : doc.end(start)]).encode("utf-8")
    ).hexdigest()


def check_hash(doc, start, expected):
    if not isinstance(expected, str) or subtree_hash(doc, start) != expected:
        raise ValueError("Subtree changed or expected_sha256 does not match; read get_record again")


def logical_text(doc, start):
    value = doc.lines[start].value
    for pos in children(doc, start):
        line = doc.lines[pos]
        if line.tag == "CONT":
            value += "\n" + line.value
        elif line.tag == "CONC":
            value += line.value
    return value


def update_value(doc, start, value, tag=None):
    """Change text, preserving every non-continuation child verbatim."""
    line = doc.lines[start]
    retained: list[str] = []
    for pos in children(doc, start):
        if doc.lines[pos].tag in {"CONT", "CONC"}:
            if doc.end(pos) != pos + 1:
                raise ValueError("Continuation has child evidence; use reviewed replace_field")
        else:
            retained.extend(part.raw for part in doc.lines[pos : doc.end(pos)])
    text = text_lines(doc, line.level, line.tag if tag is None else tag, value, line.xref)
    # Retain the selected line's original ending when no continuations are needed.
    if text.count(doc.newline) == 1:
        ending = line.raw[len(line.raw.rstrip("\r\n")) :]
        text = text.removesuffix(doc.newline) + ending
    end = doc.end(start)
    del doc.lines[start:end]
    doc.insert(start, text + "".join(retained))


def name_errors(doc):
    """New name edits must agree with their explicit components; imports may retain ambiguity."""
    errors: Counter[tuple] = Counter()
    owner = None
    for pos, line in enumerate(doc.lines):
        if line.level == 0:
            owner = line
        if line.tag != "NAME" or line.level != 1:
            continue
        if owner is None or owner.tag != "INDI":
            continue
        name = logical_text(doc, pos)
        components = {doc.lines[i].tag: logical_text(doc, i) for i in children(doc, pos)}
        surname = components.get("SURN", "")
        given = components.get("GIVN", "")
        if name.count("/") not in {0, 2}:
            errors[(owner.xref, "NAME delimiters", name)] += 1
        elif surname and (name.split("/")[1] if "/" in name else "") != surname:
            errors[(owner.xref, "SURN conflicts with NAME", name, surname)] += 1
        if given and given not in name.split("/")[0]:
            errors[(owner.xref, "GIVN conflicts with NAME", name, given)] += 1
    return errors


def update_relationship(doc, operation):
    from .structural_edits import typed_record

    family, person, role = operation["family_id"], operation["individual_id"], operation["role"]
    fam = typed_record(doc, family, "FAM")
    indi = typed_record(doc, person, "INDI")
    reciprocal = "FAMC" if role == "CHIL" else "FAMS"
    links = [
        pos
        for pos in children(doc, indi)
        if doc.lines[pos].tag == reciprocal and doc.lines[pos].value == family
    ]
    members = [
        pos
        for pos in children(doc, fam)
        if doc.lines[pos].tag == role and doc.lines[pos].value == person
    ]
    if len(links) != 1 or len(members) != 1:
        raise ValueError("Update requires a unique reciprocal relationship")
    start = links[0]
    check_hash(doc, start, operation["expected_sha256"])
    if role != "CHIL" or not {"pedigree", "status"} & operation.keys():
        raise ValueError("Provide pedigree and/or status for a CHIL relationship")
    for key, tag, choices in (
        ("pedigree", "PEDI", {"birth", "adopted", "foster", "sealing"}),
        ("status", "STAT", {"challenged", "disproven", "proven"}),
    ):
        if key not in operation:
            continue
        value = operation[key]
        if value is not None and (not isinstance(value, str) or value.lower() not in choices):
            raise ValueError(f"Invalid child-link {key}")
        matches = [pos for pos in children(doc, start) if doc.lines[pos].tag == tag]
        if len(matches) > 1:
            raise ValueError(f"Multiple {tag} fields require explicit field edits")
        if matches:
            pos = matches[0]
            if value is None:
                if doc.end(pos) != pos + 1:
                    raise ValueError("Qualifier has child evidence; use reviewed remove_field")
                del doc.lines[pos]
            else:
                update_value(doc, pos, value)
        elif value is not None:
            doc.insert(doc.end(start), text_lines(doc, doc.lines[start].level + 1, tag, value))
    return [person, family]


def field_edit(doc, operation):
    op = operation["op"]
    if op == "update_relationship":
        return update_relationship(doc, operation)
    record_id = operation["record_id"]
    if op == "add_record":
        record_id_value(doc, record_id)
        tag = tag_value(operation["tag"])
        if tag in {"HEAD", "TRLR"}:
            raise ValueError("Edit existing HEAD/TRLR fields instead of adding document envelopes")
        text = text_lines(doc, 0, tag, operation.get("value", ""), record_id)
        text += "".join(render_node(doc, node, 1) for node in operation.get("fields", []))
        doc.insert(len(doc.lines) - 1, text)
        return [record_id]
    start = doc.locate(record_id, operation.get("path", []))
    if op == "add_field":
        node = operation["field"]
        positions = [pos for pos in children(doc, start) if doc.lines[pos].tag == node["tag"]]
        index = operation.get("index")
        if index is not None and not 0 <= index <= len(positions):
            raise ValueError("index must select an existing occurrence or the next occurrence")
        at = positions[index] if index is not None and index < len(positions) else doc.end(start)
        doc.insert(at, render_node(doc, node, doc.lines[start].level + 1))
    else:
        check_hash(doc, start, operation["expected_sha256"])
        if op == "remove_record":
            if doc.lines[start].tag in {"HEAD", "TRLR", "INDI", "FAM"}:
                raise ValueError(
                    "Use person/family deletion tools; HEAD/TRLR envelopes cannot be removed"
                )
            del doc.lines[start : doc.end(start)]
        elif op == "update_field":
            if doc.lines[start].level == 0 and operation.get("tag") not in {
                None,
                doc.lines[start].tag,
            }:
                raise ValueError(
                    "Record types are stable; remove and add an auxiliary record explicitly"
                )
            update_value(doc, start, operation["value"], operation.get("tag"))
        else:
            level = doc.lines[start].level
            text = render_node(doc, operation["field"], level) if op == "replace_field" else ""
            del doc.lines[start : doc.end(start)]
            if text:
                doc.insert(start, text)
    return [record_id]
