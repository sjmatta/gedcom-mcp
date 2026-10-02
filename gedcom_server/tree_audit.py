"""Whole-document integrity checks; findings are structural, not historical proof."""

import re
from collections import Counter, defaultdict

from .document import Document

POINTER = re.compile(r"^@[^@\s]+@$")
LINK_TYPES = {
    "HUSB": "INDI",
    "WIFE": "INDI",
    "CHIL": "INDI",
    "FAMC": "FAM",
    "FAMS": "FAM",
    "SOUR": "SOUR",
    "REPO": "REPO",
    "ASSO": "INDI",
    "ALIA": "INDI",
    "NOTE": "NOTE",
    "OBJE": "OBJE",
    "SUBM": "SUBM",
    "SUBN": "SUBN",
}
REQUIRED_POINTER_TAGS = {
    "HUSB",
    "WIFE",
    "CHIL",
    "FAMC",
    "FAMS",
    "REPO",
    "ASSO",
    "ALIA",
    "SUBM",
    "SUBN",
}


def fact_signature(block):
    """Compare assertions independently of their citation/note subtrees."""
    fields = []
    skip_level = None
    for line in block:
        if skip_level is not None and line.level > skip_level:
            continue
        skip_level = None
        if line is not block[0] and line.tag in {"SOUR", "NOTE", "OBJE", "CHAN"}:
            skip_level = line.level
        else:
            fields.append((line.level, line.tag, line.value))
    return tuple(fields)


class TreeIndex:
    """Linear-time record, reference and relationship inventory, including opaque tags."""

    def __init__(self, doc):
        self.doc = doc
        self.records = {}
        self.children = defaultdict(list)
        self.references = defaultdict(list)
        self.owners = {}
        owner = "HEAD"
        for index, line in enumerate(doc.lines):
            if line.level == 0:
                owner = line.xref or line.tag
                self.records[owner] = (index, line.tag)
            self.owners[index] = owner
            if line.level == 1:
                self.children[owner].append(index)
            if POINTER.fullmatch(line.value):
                self.references[line.value].append(index)
        self.people = {key for key, (_, tag) in self.records.items() if tag == "INDI"}
        self.families = {key for key, (_, tag) in self.records.items() if tag == "FAM"}
        self.members = {key: self.values(key, {"HUSB", "WIFE", "CHIL"}) for key in self.families}
        self.links = {key: self.values(key, {"FAMC", "FAMS"}) for key in self.people}

    def values(self, key, tags):
        return [
            (self.doc.lines[i].tag, self.doc.lines[i].value)
            for i in self.children[key]
            if self.doc.lines[i].tag in tags
        ]

    def blocks(self, key):
        return [self.doc.lines[i : self.doc.end(i)] for i in self.children[key]]

    def graph(self):
        graph: dict[str, set[str]] = {key: set() for key in self.people | self.families}
        for family, members in self.members.items():
            for _, person in members:
                if person in self.people:
                    graph[family].add(person)
                    graph[person].add(family)
        for person, links in self.links.items():
            for _, family in links:
                if family in self.families:
                    graph[person].add(family)
                    graph[family].add(person)
        return graph


def audit_document(doc):
    index = TreeIndex(doc)
    issues = []

    def report(code, records, message, severity="error"):
        issues.append(
            {
                "code": code,
                "severity": severity,
                "records": sorted(set(records)),
                "message": message,
            }
        )

    parents: list[int] = []
    for pos, line in enumerate(doc.lines):
        while parents and doc.lines[parents[-1]].level >= line.level:
            parents.pop()
        parent = doc.lines[parents[-1]] if parents else None
        owner = index.owners[pos]
        if (
            line.level > 0
            and line.tag in REQUIRED_POINTER_TAGS
            and not POINTER.fullmatch(line.value)
        ):
            report("invalid_pointer_value", [owner], f"{line.tag} requires an @ID@ pointer")
        if (
            owner in index.people
            and line.level == 1
            and line.tag == "SEX"
            and line.value not in {"", "M", "F", "U"}
        ):
            report("invalid_sex_value", [owner], f"Invalid SEX value: {line.value}")
        if parent and parent.tag == "FAMC" and line.tag in {"PEDI", "STAT"}:
            choices = (
                {"", "birth", "adopted", "foster", "sealing"}
                if line.tag == "PEDI"
                else {"", "challenged", "disproven", "proven"}
            )
            if line.value.lower() not in choices:
                report(
                    "invalid_relationship_qualifier",
                    [owner],
                    f"Invalid {line.tag} value: {line.value}",
                )
        parents.append(pos)

    for target, refs in sorted(index.references.items()):
        for pos in refs:
            line = doc.lines[pos]
            owner = index.owners[pos]
            if target not in index.records:
                report(
                    "dangling_pointer", [owner, target], f"{line.tag} points to a missing record"
                )
            elif line.tag in LINK_TYPES and index.records[target][1] != LINK_TYPES[line.tag]:
                report(
                    "wrong_pointer_type",
                    [owner, target],
                    f"{line.tag} requires {LINK_TYPES[line.tag]}",
                )
    for family in sorted(index.families):
        members = index.members[family]
        for (role, person), count in Counter(members).items():
            if count > 1:
                report("duplicate_relationship", [family, person], f"{count} copies of {role}")
            expected = "FAMC" if role == "CHIL" else "FAMS"
            if person in index.people and (expected, family) not in index.links[person]:
                report("missing_reciprocal_link", [family, person], f"Missing {expected}")
        for role in ("HUSB", "WIFE"):
            if sum(tag == role for tag, _ in members) > 1:
                report("multiple_partner_role", [family], f"Multiple {role} links")
        partners = {person for role, person in members if role != "CHIL"}
        children = {person for role, person in members if role == "CHIL"}
        for person in partners & children:
            report(
                "self_parent", [family, person], "A person is both parent and child in this family"
            )
        if len(partners) < sum(role != "CHIL" for role, _ in members):
            report("duplicate_partner", [family], "Same person occupies both partner roles")
        if not members:
            report("empty_family", [family], "Family has no recorded members", "warning")
    parent_edges: dict[str, set[str]] = defaultdict(set)
    for person in sorted(index.people):
        links = index.links[person]
        for (role, family), count in Counter(links).items():
            if count > 1:
                report("duplicate_relationship", [person, family], f"{count} copies of {role}")
            expected_roles = {"CHIL"} if role == "FAMC" else {"HUSB", "WIFE"}
            if family in index.families and not any(
                (tag, person) in index.members[family] for tag in expected_roles
            ):
                report(
                    "missing_reciprocal_link",
                    [person, family],
                    f"Missing family membership for {role}",
                )
            if role == "FAMC":
                pos = next(
                    i
                    for i in index.children[person]
                    if doc.lines[i].tag == role and doc.lines[i].value == family
                )
                disproven = any(
                    line.tag == "STAT" and line.value.lower() == "disproven"
                    for line in doc.lines[pos + 1 : doc.end(pos)]
                )
                if not disproven:
                    parent_edges[person].update(
                        parent
                        for tag, parent in index.members.get(family, [])
                        if tag != "CHIL" and parent in index.people
                    )
        blocks = index.blocks(person)
        for tag in ("SEX", "BIRT", "DEAT"):
            facts = {fact_signature(block) for block in blocks if block[0].tag == tag}
            if len(facts) > 1:
                report(
                    "conflicting_facts",
                    [person],
                    f"Multiple different {tag} structures; review evidence",
                    "warning",
                )
        for block in blocks:
            if block[0].tag in {"BIRT", "DEAT"} and not any(line.tag == "SOUR" for line in block):
                report(
                    "uncited_vital_event",
                    [person],
                    f"{block[0].tag} has no source citation",
                    "warning",
                )
        if len({family for role, family in links if role == "FAMC"}) > 1:
            report(
                "multiple_parent_families",
                [person],
                "Multiple parent families; preserve qualifiers and ambiguity",
                "warning",
            )
    # Iterative DFS is bounded by the document, not Python recursion depth.
    colors: dict[str, int] = {}
    for start in sorted(index.people):
        if colors.get(start):
            continue
        path = [start]
        positions = {start: 0}
        colors[start] = 1
        stack = [iter(sorted(parent_edges[start]))]
        while stack:
            parent = next(stack[-1], None)
            if parent is None:
                finished = path.pop()
                colors[finished] = 2
                positions.pop(finished)
                stack.pop()
            elif colors.get(parent) == 1:
                report(
                    "ancestry_cycle",
                    path[positions[parent] :],
                    "Recorded parent links form an ancestry cycle",
                )
            elif not colors.get(parent):
                colors[parent] = 1
                positions[parent] = len(path)
                path.append(parent)
                stack.append(iter(sorted(parent_edges[parent])))
    graph = index.graph()
    remaining = set(graph)
    components = []
    for start in sorted(graph):
        if start not in remaining:
            continue
        pending = [start]
        remaining.remove(start)
        size = 0
        while pending:
            current = pending.pop()
            size += current in index.people
            for neighbor in graph[current] & remaining:
                remaining.remove(neighbor)
                pending.append(neighbor)
        components.append({"representative": start, "individuals": size})
    return {
        "scope": "Whole-document pointer, relationship, ancestry-cycle and evidence checks; not historical verification or a full GEDCOM standards validator",
        "complete_scan": True,
        "counts": {
            "individuals": len(index.people),
            "families": len(index.families),
            "records": len(index.records),
        },
        "summary": dict(Counter(issue["severity"] for issue in issues)),
        "issue_counts": dict(Counter(issue["code"] for issue in issues)),
        "components": components,
        "issues": issues,
    }


def error_signatures(doc):
    return Counter(
        (issue["code"], tuple(issue["records"]), issue["message"])
        for issue in audit_document(doc)["issues"]
        if issue["severity"] == "error"
    )


def audit_tree(expected_revision=None, offset=0, limit=100):
    from . import state, writes

    with state.TREE_LOCK:
        store = writes.store
        revision = store.revision if store else None
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("Stale audit revision; restart pagination")
        path = state.GEDCOM_FILE
        data = store.document(store.revision) if store else path.read_bytes() if path else None
        if data is None:
            raise ValueError("Tree is not initialized")
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("Use nonnegative offset and limit between 1 and 500")
    result = audit_document(Document(data))
    issues = result["issues"]
    result.update(
        revision=revision,
        total_issues=len(issues),
        offset=offset,
        next_offset=offset + limit if offset + limit < len(issues) else None,
    )
    result["issues"] = issues[offset : offset + limit]
    return result
