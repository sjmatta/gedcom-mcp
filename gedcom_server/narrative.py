"""Narrative content functions for LLM-friendly biography generation."""

from . import state
from .core import _normalize_lookup_id


def _get_biography(individual_id: str) -> dict | None:
    """Get a comprehensive narrative package for one person.

    Returns everything needed to understand a person's life in ONE call:
    - Vital summary
    - Birth/death facts
    - Family context with names (not IDs)
    - All events with full citation details including URLs
    - All biographical notes
    """
    lookup_id = _normalize_lookup_id(individual_id)
    indi = state.individuals.get(lookup_id)
    if not indi:
        return None

    # Build vital summary
    vital_parts = []
    if indi.birth_date or indi.birth_place:
        birth_info = "Born"
        if indi.birth_date:
            birth_info += f" {indi.birth_date}"
        if indi.birth_place:
            birth_info += f" in {indi.birth_place}"
        vital_parts.append(birth_info)
    if indi.death_date or indi.death_place:
        death_info = "Died"
        if indi.death_date:
            death_info += f" {indi.death_date}"
        if indi.death_place:
            death_info += f" in {indi.death_place}"
        vital_parts.append(death_info)
    vital_summary = ". ".join(vital_parts) + "." if vital_parts else ""

    # Get parents' names
    parents = []
    if indi.family_as_child:
        fam = state.families.get(indi.family_as_child)
        if fam:
            if fam.husband_id and fam.husband_id in state.individuals:
                parents.append(state.individuals[fam.husband_id].full_name())
            if fam.wife_id and fam.wife_id in state.individuals:
                parents.append(state.individuals[fam.wife_id].full_name())

    # Get spouses with marriage info
    spouses_info = []
    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            spouse_id = fam.wife_id if fam.husband_id == lookup_id else fam.husband_id
            if spouse_id and spouse_id in state.individuals:
                spouse_data = {"name": state.individuals[spouse_id].full_name()}
                if fam.marriage_date:
                    spouse_data["marriage_date"] = fam.marriage_date
                if fam.marriage_place:
                    spouse_data["marriage_place"] = fam.marriage_place
                spouses_info.append(spouse_data)

    # Get children's names
    children_names = []
    seen_children = set()
    for fam_id in indi.families_as_spouse:
        fam = state.families.get(fam_id)
        if fam:
            for child_id in fam.children_ids:
                if child_id not in seen_children and child_id in state.individuals:
                    seen_children.add(child_id)
                    children_names.append(state.individuals[child_id].full_name())

    # Build events with full citation details
    events_data: list[dict] = []
    for event in indi.events:
        event_dict: dict = {
            "type": event.type,
            "date": event.date,
            "place": event.place,
        }
        if event.description:
            event_dict["description"] = event.description
        if event.notes:
            event_dict["notes"] = event.notes

        # Include citations with full details
        citations_data: list[dict] = []
        for citation in event.citations:
            cite_data: dict = {
                "source": citation.source_title or citation.source_id,
            }
            if citation.page:
                cite_data["page"] = citation.page
            if citation.text:
                cite_data["text"] = citation.text
            if citation.url:
                cite_data["url"] = citation.url
            citations_data.append(cite_data)
        if citations_data:
            event_dict["citations"] = citations_data

        events_data.append(event_dict)

    return {
        "id": indi.id,
        "name": indi.full_name(),
        "vital_summary": vital_summary,
        "birth": {"date": indi.birth_date, "place": indi.birth_place},
        "death": {"date": indi.death_date, "place": indi.death_place},
        "sex": indi.sex,
        "parents": parents,
        "spouses": spouses_info,
        "children": children_names,
        "events": events_data,
        "notes": indi.notes,
    }


def _search_narrative(query: str, max_results: int = 50) -> dict:
    """Full-text search across all narrative content.

    Searches:
    - Individual-level notes (obituaries, stories, directory entries)
    - Event-level notes
    - Citation text fields
    - Source titles
    """
    query_lower = query.lower()
    results: list[dict] = []

    for indi in state.individuals.values():
        if len(results) >= max_results:
            break

        # Search individual-level notes
        for note in indi.notes:
            if query_lower in note.lower():
                # Create snippet with context
                snippet = _create_snippet(note, query_lower)
                results.append(
                    {
                        "individual_id": indi.id,
                        "individual_name": indi.full_name(),
                        "source": "note",
                        "snippet": snippet,
                        "full_text": note,
                    }
                )
                if len(results) >= max_results:
                    break

        if len(results) >= max_results:
            break

        # Search event notes and citation text
        for event in indi.events:
            if len(results) >= max_results:
                break

            # Event notes
            for note in event.notes:
                if query_lower in note.lower():
                    snippet = _create_snippet(note, query_lower)
                    results.append(
                        {
                            "individual_id": indi.id,
                            "individual_name": indi.full_name(),
                            "source": "event_note",
                            "event_type": event.type,
                            "event_date": event.date,
                            "snippet": snippet,
                            "full_text": note,
                        }
                    )
                    if len(results) >= max_results:
                        break

            if len(results) >= max_results:
                break

            # Citation text
            for citation in event.citations:
                if citation.text and query_lower in citation.text.lower():
                    snippet = _create_snippet(citation.text, query_lower)
                    results.append(
                        {
                            "individual_id": indi.id,
                            "individual_name": indi.full_name(),
                            "source": "citation_text",
                            "event_type": event.type,
                            "source_title": citation.source_title,
                            "snippet": snippet,
                            "full_text": citation.text,
                        }
                    )
                    if len(results) >= max_results:
                        break

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }


def _create_snippet(text: str, query: str, context_chars: int = 50) -> str:
    """Create a snippet with the query highlighted and surrounded by context."""
    text_lower = text.lower()
    pos = text_lower.find(query)
    if pos == -1:
        return text[:100] + "..." if len(text) > 100 else text

    start = max(0, pos - context_chars)
    end = min(len(text), pos + len(query) + context_chars)

    snippet = ""
    if start > 0:
        snippet += "..."
    # Keep original case but mark the match
    before = text[start:pos]
    match = text[pos : pos + len(query)]
    after = text[pos + len(query) : end]
    snippet += f"{before}**{match}**{after}"
    if end < len(text):
        snippet += "..."

    return snippet


def _get_repositories() -> list[dict]:
    """Get all repositories in the tree."""
    return [repo.to_dict() for repo in state.repositories.values()]
