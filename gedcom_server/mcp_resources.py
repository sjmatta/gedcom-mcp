"""MCP resource definitions for the GEDCOM genealogy server."""

from . import state
from .core import _get_family, _get_individual, _get_statistics
from .sources import _get_source, _get_sources


def register_resources(mcp):
    """Register all MCP resources with the server."""

    @mcp.resource("gedcom://individual/{id}")
    def resource_individual(id: str) -> str:
        """Get individual record by ID."""
        indi = _get_individual(id)
        if indi:
            return str(indi)
        return f"Individual {id} not found"

    @mcp.resource("gedcom://family/{id}")
    def resource_family(id: str) -> str:
        """Get family record by ID."""
        fam = _get_family(id)
        if fam:
            return str(fam)
        return f"Family {id} not found"

    @mcp.resource("gedcom://source/{id}")
    def resource_source(id: str) -> str:
        """Get source record by ID."""
        source = _get_source(id)
        if source:
            return str(source)
        return f"Source {id} not found"

    @mcp.resource("gedcom://sources")
    def resource_sources() -> str:
        """Get list of all sources."""
        source_list = _get_sources(max_results=1000)
        lines = []
        for s in source_list:
            title = s.get("title") or "Untitled"
            author = s.get("author") or "Unknown author"
            lines.append(f"{s['id']}: {title} by {author}")
        return "\n".join(lines)

    @mcp.resource("gedcom://stats")
    def resource_stats() -> str:
        """Get tree statistics."""
        return str(_get_statistics())

    @mcp.resource("gedcom://surnames")
    def resource_surnames() -> str:
        """Get list of all surnames with counts."""
        surname_counts = [(surname, len(ids)) for surname, ids in state.surname_index.items()]
        surname_counts.sort(key=lambda x: (-x[1], x[0]))  # Sort by count desc, then name
        return "\n".join(f"{surname}: {count}" for surname, count in surname_counts)
