"""Lossless graph edits, with explicit identities and no implicit branch deletion."""

import re

from .tree_audit import TreeIndex, fact_signature

FIELDS = {
    "add_family": {"op", "family_id"},
    "add_relationship": {"op", "family_id", "individual_id", "role", "pedigree", "status"},
    "remove_relationship": {"op", "family_id", "individual_id", "role", "force"},
    "delete_individual": {"op", "individual_id", "force"},
    "delete_individuals": {"op", "individual_ids", "force"},
    "delete_family": {"op", "family_id", "force"},
    "delete_families": {"op", "family_ids", "force"},
    "merge_individuals": {"op", "source_id", "target_id", "identity_evidence", "force"},
}


def typed_record(doc, key, kind):
    pos = doc.record(key)
    if doc.lines[pos].tag != kind:
        raise ValueError(f"{key} must be {kind}")
    return pos


def remove_ranges(doc, positions):
    outer: list[tuple[int, int]] = []
    for start, end in sorted(set(positions)):
        if outer and start < outer[-1][1]:
            continue
        outer.append((start, end))
    for start, end in reversed(outer):
        del doc.lines[start:end]


def rewrite_pointer(line, target):
    ending = line.raw[len(line.raw.rstrip("\r\n")) :]
    line.value = target
    line.raw = f"{line.level} {line.tag} {target}{ending}"


def relationship(doc, operation):
    family, person, role = operation["family_id"], operation["individual_id"], operation["role"]
    typed_record(doc, family, "FAM")
    typed_record(doc, person, "INDI")
    if role not in {"HUSB", "WIFE", "CHIL"}:
        raise ValueError("role must be HUSB, WIFE or CHIL; role does not infer sex")
    reciprocal = "FAMC" if role == "CHIL" else "FAMS"
    index = TreeIndex(doc)
    member = [
        i
        for i in index.children[family]
        if doc.lines[i].tag == role and doc.lines[i].value == person
    ]
    links = [
        i
        for i in index.children[person]
        if doc.lines[i].tag == reciprocal and doc.lines[i].value == family
    ]
    if operation["op"] == "remove_relationship":
        if not member and not links:
            raise ValueError("Relationship does not exist")
        # A FAMS belongs to either partner role; keep it if the other role remains.
        other = any(
            tag != role and tag in {"HUSB", "WIFE"} and key == person
            for tag, key in index.members[family]
        )
        if not member and other:
            raise ValueError("Requested partner role does not exist")
        positions = member + ([] if other and role != "CHIL" else links)
        if not operation.get("force", False) and any(
            line.tag not in {"PEDI", "STAT"}
            for pos in positions
            for line in doc.lines[pos + 1 : doc.end(pos)]
        ):
            raise ValueError("Relationship has subordinate evidence; review and use force=true")
        remove_ranges(doc, [(i, doc.end(i)) for i in positions])
    else:
        if member or links:
            raise ValueError(
                "Relationship already exists or is one-sided; remove it before replacing"
            )
        if role != "CHIL" and any(tag == role for tag, _ in index.members[family]):
            raise ValueError("Partner role is occupied; remove the old relationship first")
        if any(key == person for _, key in index.members[family]):
            raise ValueError("Person already has a different role in this family")
        text = f"1 {reciprocal} {family}{doc.newline}"
        for key, tag, choices in [
            ("pedigree", "PEDI", {"birth", "adopted", "foster", "sealing"}),
            ("status", "STAT", {"challenged", "disproven", "proven"}),
        ]:
            if key in operation:
                value = operation[key]
                if role != "CHIL" or not isinstance(value, str) or value.lower() not in choices:
                    raise ValueError(f"Invalid child-link {key}")
                text += f"2 {tag} {value}{doc.newline}"
        doc.insert(doc.end(doc.record(person)), text)
        doc.insert(doc.end(doc.record(family)), f"1 {role} {person}{doc.newline}")
    return [family, person]


def delete_people(doc, people, force=False):
    if (
        not isinstance(people, list)
        or not 1 <= len(people) <= 50000
        or any(not isinstance(key, str) for key in people)
        or len(set(people)) != len(people)
    ):
        raise ValueError("Provide 1–50000 unique individual IDs")
    index = TreeIndex(doc)
    for person in people:
        if person not in index.people:
            raise ValueError(f"{person} must be an existing INDI")
    deleted = set(people)
    ranges = [(index.records[person][0], doc.end(index.records[person][0])) for person in people]
    affected = list(people)
    for person in people:
        for pos in index.references[person]:
            owner = index.owners[pos]
            line = doc.lines[pos]
            if owner in deleted:
                continue
            if not force and (
                owner not in index.families
                or line.level != 1
                or line.tag not in {"HUSB", "WIFE", "CHIL"}
            ):
                raise ValueError(
                    f"Deletion blocked by reference from {owner} ({line.tag}); resolve explicitly"
                )
            # Subordinate evidence must be reviewed separately, never silently discarded.
            if not force and doc.end(pos) != pos + 1:
                raise ValueError(f"Deletion blocked by evidence under {owner} {line.tag}")
            ranges.append((pos, doc.end(pos)))
            affected.append(owner)
    remove_ranges(doc, ranges)
    return affected


def merge_people(doc, operation):
    source, target = operation["source_id"], operation["target_id"]
    if source == target:
        raise ValueError("Merge requires distinct people")
    typed_record(doc, source, "INDI")
    typed_record(doc, target, "INDI")
    doc.value(operation.get("identity_evidence"))
    if not isinstance(operation.get("force", False), bool):
        raise ValueError("force must be boolean")
    index = TreeIndex(doc)
    source_blocks, target_blocks = index.blocks(source), index.blocks(target)
    conflicts = []
    for tag in ("NAME", "SEX", "BIRT", "DEAT"):
        first = {fact_signature(block) for block in source_blocks if block[0].tag == tag}
        second = {fact_signature(block) for block in target_blocks if block[0].tag == tag}
        if first and second and first != second:
            conflicts.append(tag)
    if conflicts and not operation.get("force", False):
        raise ValueError(
            f"Merge has differing {', '.join(conflicts)}; review evidence and use force=true after review to retain both"
        )
    # Redirect every pointer, including unknown tags and nested source/note references.
    affected = [source, target]
    for pos in index.references[source]:
        rewrite_pointer(doc.lines[pos], target)
        affected.append(index.owners[pos])
    # Gather blocks after pointer redirection and retain every distinct structure.
    index = TreeIndex(doc)
    existing = {"".join(line.raw for line in block) for block in index.blocks(target)}
    extra = ""
    for block in index.blocks(source):
        raw = "".join(line.raw for line in block)
        if raw not in existing:
            extra += raw
            existing.add(raw)
    doc.insert(doc.end(doc.record(target)), extra)
    start = doc.record(source)
    del doc.lines[start : doc.end(start)]
    # Identical relationship structures can coalesce. Differing qualifiers/evidence
    # cannot be discarded just because their pointers match.
    index = TreeIndex(doc)
    removals = []
    for record in set(affected) - {source}:
        if record not in index.records:
            continue
        seen: dict[tuple[str, str], str] = {}
        for pos in index.children[record]:
            block = doc.lines[pos : doc.end(pos)]
            line = block[0]
            if line.tag not in {"FAMC", "FAMS", "HUSB", "WIFE", "CHIL"}:
                continue
            key = (line.tag, line.value)
            raw = "".join(part.raw for part in block)
            if key in seen:
                if seen[key] != raw:
                    raise ValueError(
                        f"Merge conflicts with relationship qualifiers/evidence in {record}"
                    )
                removals.append((pos, doc.end(pos)))
            else:
                seen[key] = raw
    remove_ranges(doc, removals)
    return affected


def structural_edit(doc, operation):
    op = operation["op"]
    force = operation.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("force must be boolean")
    if set(operation) - FIELDS[op]:
        raise ValueError("Unsupported structural operation fields")
    if op == "add_family":
        family = operation["family_id"]
        if not isinstance(family, str) or not re.fullmatch(r"@[^@\s]+@", family):
            raise ValueError("family_id must be a GEDCOM cross-reference")
        if family in TreeIndex(doc).records:
            raise ValueError("Record ID already exists")
        doc.insert(len(doc.lines) - 1, f"0 {family} FAM{doc.newline}")
        return [family]
    if op in {"add_relationship", "remove_relationship"}:
        return relationship(doc, operation)
    if op == "delete_individual":
        return delete_people(doc, [operation["individual_id"]], force)
    if op == "delete_individuals":
        return delete_people(doc, operation["individual_ids"], force)
    if op == "merge_individuals":
        return merge_people(doc, operation)
    families = operation["family_ids"] if op == "delete_families" else [operation["family_id"]]
    if (
        not isinstance(families, list)
        or not 1 <= len(families) <= 50000
        or any(not isinstance(key, str) for key in families)
        or len(set(families)) != len(families)
    ):
        raise ValueError("Provide 1–50000 unique family IDs")
    index = TreeIndex(doc)
    deleted = set(families)
    for family in families:
        if family not in index.families:
            raise ValueError(f"{family} must be an existing FAM")
        external_refs = any(index.owners[pos] not in deleted for pos in index.references[family])
        if external_refs or index.members[family] or (index.children[family] and not force):
            raise ValueError(
                "Family must be unreferenced and have no members; evidence/metadata requires force=true after review"
            )
    remove_ranges(
        doc, [(index.records[family][0], doc.end(index.records[family][0])) for family in families]
    )
    return families
