"""Explicit parent-family selection and bounded relationship explanations."""

from collections import defaultdict, deque
from typing import Literal

from . import state
from .core import _ancestor_name, _descendant_name, _normalize_lookup_id, _ordinal
from .models import ParentFamily

Lineage = Literal["default", "birth", "adopted", "foster", "sealing", "all"]
MAX_PATH_NODES = 50000
MAX_GRAPH_EDGES = 200000


def parent_links(individual_id: str, lineage: Lineage = "default") -> list[ParentFamily]:
    if lineage not in ("default", "birth", "adopted", "foster", "sealing", "all"):
        raise ValueError("Unknown lineage selection")
    indi = state.individuals[individual_id]
    links = indi.parent_families or (
        [ParentFamily(indi.family_as_child)] if indi.family_as_child else []
    )
    links = [link for link in links if (link.status or "").lower() != "disproven"]
    if lineage == "default":
        return [link for link in links if link.family_id == indi.family_as_child]
    if lineage == "all":
        return links
    return [link for link in links if (link.pedigree or "").lower() == lineage]


def _get_parent_families(individual_id: str) -> dict:
    indi = state.individuals.get(_normalize_lookup_id(individual_id))
    if not indi:
        return {"error": "Individual not found", "parent_families": []}
    return {
        "individual": indi.to_summary(),
        "selected_family_id": indi.family_as_child,
        "selection": indi.parent_selection,
        "parent_families": [
            {
                **link.to_dict(),
                "family": state.families[link.family_id].to_dict()
                if link.family_id in state.families
                else None,
            }
            for link in (indi.parent_families or parent_links(indi.id))
        ],
        "note": "Pedigree qualifiers are imported assertions; birth does not prove genetic parentage.",
    }


def _path_label(steps: list[dict]) -> str:
    directions = [step["direction"] for step in steps]
    if not directions:
        return "same person"
    if directions == ["spouse"]:
        return "spouse"
    if "spouse" in directions:
        return "relative by marriage (see path)"
    up = 0
    while up < len(directions) and directions[up] == "parent":
        up += 1
    down = len(directions) - up
    if any(direction != "child" for direction in directions[up:]):
        return "family connection (see path)"
    if down == 0:
        label = _descendant_name(up)
    elif up == 0:
        label = _ancestor_name(down)
    elif up == down == 1:
        label = "sibling or half-sibling"
    elif min(up, down) == 1:
        label = "niece/nephew" if up > down else "aunt/uncle"
        if abs(up - down) > 1:
            label = f"{abs(up - down) - 1}x great-{label}"
    else:
        degree, removal = min(up, down) - 1, abs(up - down)
        label = f"{_ordinal(degree)} cousin"
        if removal:
            label += f" {removal}x removed"
    if any((step.get("pedigree") or "").lower() not in ("", "birth") for step in steps):
        return f"{label} through qualified parent links (see pedigree in path)"
    return label


def _get_relationship_to_me(
    individual_id: str, lineage: Lineage = "default", max_steps: int = 30
) -> dict:
    """Return the person's relationship to the home person and its record path.

    Searches one shortest family path, not all possible relationships. Edge
    directions describe the next person; the label describes person 1 relative
    to the home person. No parent qualifier is silently treated as biological.
    """
    start = _normalize_lookup_id(individual_id)
    home = state.HOME_PERSON_ID
    if start not in state.individuals or home not in state.individuals:
        return {"error": "Individual or configured home person not found", "path": []}
    if not 1 <= max_steps <= 100:
        raise ValueError("max_steps must be between 1 and 100")
    if lineage not in ("default", "birth", "adopted", "foster", "sealing", "all"):
        raise ValueError("Unknown lineage selection")
    base = {
        "individual": state.individuals[start].to_summary(),
        "home_person": state.individuals[home].to_summary(),
        "lineage": lineage,
        "max_steps": max_steps,
        "note": "One shortest recorded family path; qualifiers are not proof of genetic parentage.",
    }
    graph: dict[str, list[dict]] = defaultdict(list)
    edge_count = 0

    def connect(first: str, second: str, forward: str, reverse: str, **evidence):
        nonlocal edge_count
        if first not in state.individuals or second not in state.individuals or first == second:
            return
        if edge_count >= MAX_GRAPH_EDGES:
            raise ValueError("Relationship search incomplete: edge budget exceeded")
        graph[first].append({"to_id": second, "direction": forward, **evidence})
        graph[second].append({"to_id": first, "direction": reverse, **evidence})
        edge_count += 2

    for id_ in state.individuals:
        for link in parent_links(id_, lineage):
            fam = state.families.get(link.family_id)
            if fam:
                for parent in (fam.husband_id, fam.wife_id):
                    if parent:
                        connect(id_, parent, "parent", "child", **link.to_dict())
    for fam in state.families.values():
        if fam.husband_id and fam.wife_id:
            connect(fam.husband_id, fam.wife_id, "spouse", "spouse", family_id=fam.id)

    previous: dict[str, tuple[str, dict] | None] = {start: None}
    queue = deque([(start, 0)])
    limited = False
    while queue:
        current, depth = queue.popleft()
        if current == home:
            steps = []
            while (entry := previous[current]) is not None:
                prior, edge = entry
                steps.append(
                    {
                        "from_id": prior,
                        **edge,
                        "from_name": state.individuals[prior].full_name(),
                        "to_name": state.individuals[current].full_name(),
                    }
                )
                current = prior
            steps.reverse()
            return {
                **base,
                "relationship": _path_label(steps),
                "path": steps,
                "truncated": False,
                "visited_count": len(previous),
            }
        for edge in graph[current]:
            next_id = edge["to_id"]
            if next_id in previous:
                continue
            if depth >= max_steps:
                limited = True
                continue
            if len(previous) >= MAX_PATH_NODES:
                return {
                    **base,
                    "relationship": None,
                    "path": [],
                    "truncated": True,
                    "error": "Relationship search incomplete: node budget exceeded",
                }
            previous[next_id] = current, edge
            queue.append((next_id, depth + 1))
    return {
        **base,
        "relationship": None,
        "path": [],
        "truncated": limited,
        "message": "No path found with this lineage selection and search limit.",
        "visited_count": len(previous),
    }
