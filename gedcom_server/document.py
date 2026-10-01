"""Lossless UTF-8 GEDCOM editing; query dataclasses are never serialized.

Existing lines (including unknown tags and line endings) are retained verbatim.
Structural edits preserve evidence and update reciprocal links atomically.
"""

import difflib
import re
import uuid
from dataclasses import dataclass

from .constants import EVENT_TAGS, FAMILY_EVENT_TAGS
from .editing import EditResult

LINE = re.compile(r"^(\d+) (?:(@[^@\s]+@) )?([A-Za-z0-9_]+)(?: (.*))?$")


@dataclass
class Line:
    raw: str
    level: int
    xref: str | None
    tag: str
    value: str


class Document:
    def __init__(self, data: bytes):
        text = data.decode("utf-8-sig")
        self.bom = data.startswith(b"\xef\xbb\xbf")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines: list[Line] = []
        previous = -1
        ids = set()
        for raw in re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text):
            if not raw:
                continue
            match = LINE.fullmatch(raw.rstrip("\r\n"))
            if not match:
                raise ValueError("Malformed GEDCOM line")
            level, xref, tag, value = match.groups()
            number = int(level)
            if number > previous + 1 or (xref and (number != 0 or xref in ids)):
                raise ValueError("Invalid GEDCOM nesting or duplicate record ID")
            if xref:
                ids.add(xref)
            self.lines.append(Line(raw, number, xref, tag, value or ""))
            previous = number
        if not self.lines or self.lines[0].tag != "HEAD" or self.lines[-1].tag != "TRLR":
            raise ValueError("GEDCOM must start with HEAD and end with TRLR")
        if self.lines[0].level != 0 or self.lines[-1].level != 0:
            raise ValueError("HEAD and TRLR must be level zero")
        if any(line.tag == "CHAR" and line.value.upper() != "UTF-8" for line in self.lines):
            raise ValueError("Writes currently require UTF-8 GEDCOM; baseline is never converted")

    def bytes(self) -> bytes:
        return (b"\xef\xbb\xbf" if self.bom else b"") + "".join(
            line.raw for line in self.lines
        ).encode("utf-8")

    def end(self, start: int) -> int:
        level = self.lines[start].level
        return next(
            (i for i in range(start + 1, len(self.lines)) if self.lines[i].level <= level),
            len(self.lines),
        )

    def record(self, record_id: str) -> int:
        for i, line in enumerate(self.lines):
            if line.xref == record_id:
                return i
        raise ValueError(f"Record not found: {record_id}")

    def locate(self, record_id: str, path: list[dict]) -> int:
        """Path components select a tag and zero-based occurrence among siblings."""
        current = self.record(record_id)
        for part in path:
            if set(part) != {"tag", "index"} or not isinstance(part["index"], int):
                raise ValueError("Each path component requires tag and integer index")
            choices = [
                i
                for i in range(current + 1, self.end(current))
                if self.lines[i].level == self.lines[current].level + 1
                and self.lines[i].tag == part["tag"]
            ]
            if part["index"] < 0 or part["index"] >= len(choices):
                raise ValueError("Path does not identify an existing field")
            current = choices[part["index"]]
        return current

    def insert(self, at: int, text: str) -> None:
        if at and not self.lines[at - 1].raw.endswith(("\n", "\r")):
            raise ValueError("Cannot append to an unterminated GEDCOM line")
        for raw in reversed(
            [part for part in re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text) if part]
        ):
            match = LINE.fullmatch(raw.rstrip("\r\n"))
            assert match
            level, xref, tag, value = match.groups()
            self.lines.insert(at, Line(raw, int(level), xref, tag, value or ""))

    @staticmethod
    def value(value: object, *, required: bool = True) -> str:
        if not isinstance(value, str) or (required and not value.strip()):
            raise ValueError("A nonempty text value is required")
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or len(value.encode()) > 200:
            raise ValueError("Values must be single-line text, at most 200 UTF-8 bytes")
        return value

    def citation(self, source_id: str, level: int, page: str = "") -> str:
        if self.lines[self.record(source_id)].tag != "SOUR":
            raise ValueError("Citation must reference a source record")
        text = f"{level} SOUR {source_id}{self.newline}"
        if page:
            text += f"{level + 1} PAGE {self.value(page)}{self.newline}"
        return text

    def edit(self, operations: list[dict]) -> list[str]:
        from .structural_edits import FIELDS, structural_edit
        from .tree_audit import error_signatures

        if not operations or len(operations) > 50:
            raise ValueError("Provide between 1 and 50 operations")
        affected = []
        structural = any(operation.get("op") in FIELDS for operation in operations)
        original_errors = error_signatures(self) if structural else None
        allowed = {
            "add_source": {"op", "title", "author", "publication"},
            "add_note": {"op", "record_id", "text"},
            "add_event": {
                "op",
                "record_id",
                "tag",
                "date",
                "place",
                "description",
                "source_id",
                "page",
            },
            "add_citation": {"op", "record_id", "path", "source_id", "page"},
            "replace_value": {"op", "record_id", "path", "old_value", "value"},
        }
        for operation in operations:
            op = operation.get("op")
            if op in FIELDS:
                affected.extend(structural_edit(self, operation))
                continue
            if op not in allowed or set(operation) - allowed[op]:
                raise ValueError("Unsupported operation or fields")
            if op == "add_source":
                record_id = f"@S{uuid.uuid4().hex}@"
                text = f"0 {record_id} SOUR{self.newline}1 TITL {self.value(operation.get('title'))}{self.newline}"
                for key, tag in (("author", "AUTH"), ("publication", "PUBL")):
                    if operation.get(key):
                        text += f"1 {tag} {self.value(operation[key])}{self.newline}"
                self.insert(len(self.lines) - 1, text)
            else:
                record_id = operation["record_id"]
                start = self.record(record_id)
                kind = self.lines[start].tag
                if kind not in {"INDI", "FAM"}:
                    raise ValueError("Edits require an individual or family record")
                if op == "add_note":
                    text = self.value(operation.get("text"))
                    self.insert(self.end(start), f"1 NOTE {text}{self.newline}")
                elif op == "add_event":
                    tag = operation["tag"]
                    if tag not in (EVENT_TAGS if kind == "INDI" else FAMILY_EVENT_TAGS):
                        raise ValueError("Unsupported event tag")
                    # Dates/places never become uncited facts through this operation.
                    citation = self.citation(operation["source_id"], 2, operation.get("page", ""))
                    description = self.value(operation.get("description", ""), required=False)
                    text = f"1 {tag}{' ' + description if description else ''}{self.newline}"
                    for key, subtag in (("date", "DATE"), ("place", "PLAC")):
                        if operation.get(key):
                            text += f"2 {subtag} {self.value(operation[key])}{self.newline}"
                    self.insert(self.end(start), text + citation)
                elif op == "add_citation":
                    path = operation["path"]
                    target = self.locate(record_id, path)
                    if len(path) != 1 or self.lines[target].tag not in set(EVENT_TAGS) | set(
                        FAMILY_EVENT_TAGS
                    ):
                        raise ValueError("Citations currently target a level-one event")
                    self.insert(
                        self.end(target),
                        self.citation(operation["source_id"], 2, operation.get("page", "")),
                    )
                elif op == "replace_value":
                    path = operation["path"]
                    target = self.locate(record_id, path)
                    line = self.lines[target]
                    editable = (len(path) == 1 and line.tag in {"NAME", "SEX"}) or (
                        len(path) == 2
                        and path[0]["tag"] in set(EVENT_TAGS) | set(FAMILY_EVENT_TAGS)
                        and line.tag in {"DATE", "PLAC"}
                    )
                    if not editable or line.value != operation["old_value"]:
                        raise ValueError("Field is not editable or old value does not match")
                    # NAME's subordinate GIVN/SURN could contradict the edited value.
                    if self.end(target) != target + 1:
                        raise ValueError("Field has child tags; use a future structured edit")
                    value = self.value(operation.get("value"))
                    if line.tag == "SEX" and value not in {"M", "F", "U"}:
                        raise ValueError("SEX must be M, F, or U")
                    ending = line.raw[len(line.raw.rstrip("\r\n")) :]
                    line.raw = f"{line.level} {line.tag} {value}{ending}"
                    line.value = value
            affected.append(record_id)
        # Validate our output independently of the editing logic.
        Document(self.bytes())
        if original_errors is not None:
            introduced = error_signatures(self) - original_errors
            if introduced:
                raise ValueError(
                    f"Structural edit introduces integrity errors: {list(introduced)[:10]}"
                )
        return list(dict.fromkeys(affected))


class LosslessEditor:
    """Current GedcomEditor adapter; all GEDCOM syntax handling lives here."""

    def validate(self, data: bytes) -> None:
        Document(data)

    def apply(self, data: bytes, operations: list[dict]) -> EditResult:
        document = Document(data)
        affected = document.edit(operations)
        review = {
            "force_operation_indexes": [i for i, op in enumerate(operations) if op.get("force")],
            "merge_identity_evidence": [
                {key: op[key] for key in ("source_id", "target_id", "identity_evidence")}
                for op in operations
                if op["op"] == "merge_individuals"
            ],
        }
        return EditResult(document.bytes(), tuple(affected), review)

    def records(self, data: bytes) -> list[bytes]:
        document = Document(data)
        chunks: list[bytes] = []
        for line in document.lines:
            raw = line.raw.encode("utf-8")
            if line.level == 0:
                chunks.append(raw)
            else:
                chunks[-1] += raw
        if document.bom:
            chunks[0] = b"\xef\xbb\xbf" + chunks[0]
        return chunks

    @staticmethod
    def _blocks(data: bytes) -> dict[str, str]:
        text = data.decode("utf-8-sig")
        starts = [match.start() for match in re.finditer(r"(?m)^0 ", text)]
        blocks = {}
        anonymous_counts: dict[str, int] = {}
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(text)
            block = text[start:end]
            match = re.match(r"0 (@[^@\s]+@) ", block)
            if match:
                key = match.group(1)
            else:
                tag = block.split()[1]
                occurrence = anonymous_counts.get(tag, 0)
                anonymous_counts[tag] = occurrence + 1
                key = f"anonymous-{tag}-{occurrence}"
            blocks[key] = block
        return blocks

    def diff(self, before: bytes, after: bytes, affected: list[str] | None) -> list[str]:
        old_blocks, new_blocks = self._blocks(before), self._blocks(after)
        # Include every changed block, even header pointers rewritten by forced deletion.
        keys = list(dict.fromkeys([*old_blocks, *new_blocks]))
        difference: list[str] = []
        for key in keys:
            old, new = old_blocks.get(key, ""), new_blocks.get(key, "")
            if old != new:
                difference.extend(
                    difflib.unified_diff(
                        old.split("\n"),
                        new.split("\n"),
                        fromfile=f"before:{key}",
                        tofile=f"proposed:{key}",
                        lineterm="",
                    )
                )
        return difference
