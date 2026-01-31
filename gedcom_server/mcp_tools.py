"""MCP tool definitions for the GEDCOM genealogy server."""

from .core import (
    _detect_pedigree_collapse,
    _get_ancestors,
    _get_children,
    _get_descendants,
    _get_family,
    _get_home_person,
    _get_individual,
    _get_parents,
    _get_relationship,
    _get_siblings,
    _get_spouses,
    _get_statistics,
    _get_surname_origins,
    _search_individuals,
    _traverse,
)
from .events import _get_military_service, _get_timeline
from .narrative import _get_biography
from .places import _get_place_cluster
from .query import _query
from .semantic import _semantic_search
from .spatial import _search_nearby


def register_tools(mcp):
    """Register all MCP tools with the server."""

    # ============== CONTEXT TOOLS (2) ==============

    @mcp.tool()
    def get_home_person() -> dict | None:
        """
        Get the home person (tree owner) - Stephen John Matta (1984).

        This is the essential starting point for "my ancestors" queries.
        Use this first to establish context for genealogy exploration.

        Returns:
            Full individual record for the home person
        """
        return _get_home_person()

    @mcp.tool()
    def get_statistics() -> dict:
        """
        Get statistics about the genealogy tree.

        Provides tree overview and orientation: total individuals, families,
        date ranges, gender breakdown, and top surnames.

        Returns:
            Dictionary with counts, date ranges, and other statistics
        """
        return _get_statistics()

    # ============== LOOKUP TOOLS (3) ==============

    @mcp.tool()
    def get_individual(individual_id: str) -> dict | None:
        """
        Get basic details for an individual by their GEDCOM ID.

        Lightweight lookup - returns basic record with family link IDs.
        Use get_biography() when you need full context (events, notes, sources).

        Args:
            individual_id: The GEDCOM ID (e.g., "I123" or "@I123@")

        Returns:
            Individual record with name, dates, places, and family IDs
        """
        return _get_individual(individual_id)

    @mcp.tool()
    def get_biography(individual_id: str) -> dict | None:
        """
        Get comprehensive narrative package for one person.

        Heavy/full context - returns everything needed for biographical narrative:
        - vital_summary: Quick "Born X. Died Y." summary
        - birth/death: Full date and place info
        - parents/spouses/children: Family names (not IDs) for easy narrative use
        - events: All life events with full citation details including URLs
        - notes: All biographical notes (obituaries, baptism records, etc.)

        Use get_individual() for lightweight scanning of many people.
        Use this when diving deep into one person.

        Args:
            individual_id: The GEDCOM ID (e.g., "I123" or "@I123@")

        Returns:
            Complete biography dict or None if not found
        """
        return _get_biography(individual_id)

    @mcp.tool()
    def get_family(family_id: str) -> dict | None:
        """
        Get family unit information by GEDCOM family ID.

        Returns the family record with husband, wife, and children.

        Args:
            family_id: The GEDCOM family ID (e.g., "F123" or "@F123@")

        Returns:
            Family record with husband, wife, children IDs and marriage info
        """
        return _get_family(family_id)

    # ============== NAVIGATION TOOLS (6) ==============

    @mcp.tool()
    def get_parents(individual_id: str) -> dict | None:
        """
        Get the parents of an individual.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            Dictionary with father and mother info, or None if not found
        """
        return _get_parents(individual_id)

    @mcp.tool()
    def get_children(individual_id: str) -> list[dict]:
        """
        Get all children of an individual (from all marriages/partnerships).

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of children with summary info
        """
        return _get_children(individual_id)

    @mcp.tool()
    def get_spouses(individual_id: str) -> list[dict]:
        """
        Get all spouses/partners of an individual.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of spouses with summary info and marriage details
        """
        return _get_spouses(individual_id)

    @mcp.tool()
    def get_siblings(individual_id: str) -> list[dict]:
        """
        Get siblings of an individual (same parents).

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of siblings with summary info
        """
        return _get_siblings(individual_id)

    @mcp.tool()
    def get_ancestors(
        individual_id: str,
        generations: int = 4,
        filter: str | None = None,
    ) -> dict | list[dict]:
        """
        Get ancestor tree up to N generations.

        Args:
            individual_id: The GEDCOM ID of the individual
            generations: Number of generations to retrieve (default 4, max 20)
            filter: Optional filter:
                - None: Return full nested tree (default)
                - "terminal": Return only end-of-line ancestors (brick walls/oldest known)

        Returns:
            If filter is None: Nested dictionary representing the ancestor tree
            If filter is "terminal": List of terminal ancestors with generation and path

        Examples:
            get_ancestors("@I123@", 4)  # Standard 4-generation tree
            get_ancestors("@I123@", 20, "terminal")  # Find oldest known ancestors
        """
        return _get_ancestors(individual_id, generations, filter)

    @mcp.tool()
    def get_descendants(individual_id: str, generations: int = 4) -> dict:
        """
        Get descendant tree up to N generations.

        Args:
            individual_id: The GEDCOM ID of the individual
            generations: Number of generations to retrieve (default 4, max 10)

        Returns:
            Nested dictionary representing the descendant tree
        """
        return _get_descendants(individual_id, generations)

    # ============== SEARCH TOOLS (1) ==============

    @mcp.tool()
    def search_individuals(name: str, max_results: int = 50) -> list[dict]:
        """
        Search for individuals by name (partial match on given name or surname).

        Args:
            name: Name to search for (case-insensitive partial match)
            max_results: Maximum number of results to return (default 50)

        Returns:
            List of matching individuals with summary info
        """
        return _search_individuals(name, max_results)

    # ============== RELATIONSHIP TOOLS (2) ==============

    @mcp.tool()
    def get_relationship(
        id1: str,
        id2: str,
        max_generations: int | None = 10,
    ) -> dict:
        """
        Calculate and name the relationship between two individuals.

        Detects these relationship types:
        - Direct lineage: parent, grandparent, great-grandparent, 2nd great-grandparent,
          ..., 19th great-grandparent, etc. (unlimited depth)
        - Direct descendants: child, grandchild, great-grandchild, etc.
        - Siblings: sibling, half-sibling
        - Extended: spouse, aunt/uncle, niece/nephew
        - Cousins: first cousin, second cousin once removed, etc.

        Args:
            id1: GEDCOM ID of first individual
            id2: GEDCOM ID of second individual
            max_generations: How far back to search for common ancestors.
                Pass null/None for unlimited depth (searches up to 100 generations).

        Returns:
            Dict with both individuals' info, relationship name, and
            common ancestor info for cousin relationships

        Examples:
            get_relationship("@I123@", "@I456@")  # Default 10-generation search
            get_relationship("@I123@", "@I456@", null)  # Unlimited search depth
        """
        return _get_relationship(id1, id2, max_generations)

    @mcp.tool()
    def detect_pedigree_collapse(individual_id: str, max_generations: int = 10) -> dict:
        """
        Detect pedigree collapse (ancestors appearing multiple times).

        Pedigree collapse occurs when ancestors appear multiple times in a family
        tree, typically due to cousin marriages or other intermarriage within
        a community. This is a discovery feature for finding interesting patterns.

        Args:
            individual_id: GEDCOM ID of the individual
            max_generations: Max generations to search (default 10)

        Returns:
            Dict with individual info and list of collapse points showing
            which ancestors appear multiple times and through which paths
        """
        return _detect_pedigree_collapse(individual_id, max_generations)

    # ============== PRIMITIVES (1) ==============

    @mcp.tool()
    def traverse(
        individual_id: str,
        direction: str,
        depth: int = 1,
    ) -> list[dict]:
        """
        Generic graph traversal for advanced/custom navigation.

        Use this when you need multi-level traversal beyond what the specific
        navigation tools provide. Performs breadth-first traversal.

        Args:
            individual_id: Starting person's GEDCOM ID
            direction: "parents" | "children" | "spouses" | "siblings"
            depth: How many levels to traverse (default 1, max 10)

        Returns:
            List of individuals found, each with a "level" field indicating depth

        Examples:
            traverse("@I123@", "children", 2)  # Children and grandchildren
            traverse("@I123@", "parents", 3)   # Parents, grandparents, great-grandparents
            traverse("@I123@", "siblings", 1)  # Just siblings
        """
        return _traverse(individual_id, direction, depth)

    # ============== NON-AGENT CLIENTS (1) ==============

    @mcp.tool()
    def query(question: str) -> str:
        """
        Answer a natural language question about the family tree.

        IMPORTANT: This tool is a FALLBACK for MCP clients that lack subagent
        capabilities. If your client supports spawning subagents/subtasks,
        use those instead - they will be more capable and have access to
        your full toolset. This tool runs a simple internal reasoning loop
        that is less powerful than a proper subagent.

        Use this tool ONLY when:
        - Your MCP client does not support subagents
        - You need to investigate genealogy data without filling context
          with intermediate tool calls

        For simple lookups or when you need structured data, use the
        individual tools (get_biography, get_ancestors, etc.) instead.

        Examples:
            "Who are Stephen's maternal grandparents?"
            "Trace my ancestry back 4 generations and summarize"
            "How are @I123@ and @I456@ related?"
            "What do we know about everyone named Smith?"
            "Create a narrative of my family history"

        Args:
            question: Natural language question about the genealogy data

        Returns:
            Prose answer to the question
        """
        return _query(question)

    # ============== SEMANTIC SEARCH (1) ==============

    @mcp.tool()
    def semantic_search(query: str, max_results: int = 20) -> dict:
        """
        Search for individuals using natural language semantic matching.

        Finds people based on meaning, not keywords. Works best for conceptual
        queries that traditional text search would miss.

        Examples:
            "served in Civil War"
            "emigrated from Ireland"
            "died in childbirth"
            "coal miners in Pennsylvania"
            "farmers in Scotland"

        Requires SEMANTIC_SEARCH_ENABLED=true environment variable.
        Results include individual IDs usable with get_biography() for full details.

        Args:
            query: Natural language description of what you're looking for
            max_results: Max results to return (default 20, max 100)

        Returns:
            Dictionary with query, result_count, and results list containing
            individual_id, name, birth_date, death_date, relevance_score, and snippet
        """
        return _semantic_search(query, max_results)

    # ============== GIS SEARCH (1) ==============

    @mcp.tool()
    def search_nearby(
        location: str,
        radius_miles: float = 50,
        event_types: list[str] | None = None,
        unit: str = "miles",
        max_results: int = 100,
        mode: str = "proximity",
    ) -> dict:
        """
        Find individuals with events near or within a location.

        Supports two search modes:
        - "proximity" (default): Find people within X miles of a point
        - "within": Find people with events inside a region's bounding box

        Examples:
            search_nearby("Pittsburgh", 50)  # Within 50 miles of Pittsburgh
            search_nearby("Benkovce", 25, ["BIRT"])  # Births within 25 miles
            search_nearby("New York", mode="within")  # Everyone inside NY State
            search_nearby("California", mode="within", event_types=["BIRT"])  # Births in CA

        GIS search is enabled by default. Background geocoding runs at startup
        to populate coordinates for all places in the tree.

        Args:
            location: Place name to search around (fuzzy matched)
            radius_miles: Search radius (default 50, max 500) - ignored when mode="within"
            event_types: Optional filter - list of event types like ["BIRT", "DEAT", "MARR"]
            unit: Distance unit - "miles" (default) or "km"
            max_results: Maximum results to return (default 100)
            mode: Search mode - "proximity" (default) or "within"
                - proximity: Find people within X miles of the location's center point
                - within: Find people with events inside the location's bounding box

        Returns:
            Dictionary with:
            - reference_location: matched place with coordinates/bbox and confidence
            - mode: the search mode used ("proximity" or "within")
            - search_radius_miles: the search radius (proximity mode only)
            - geocoding_status: "running", "complete", or "disabled"
            - coverage: how many places were successfully geocoded
            - coverage_note: explanation that results may be incomplete
            - result_count: number of matches found
            - results: list of individuals with distance (proximity) or matching events
        """
        return _search_nearby(
            location=location,
            radius_miles=radius_miles,
            event_types=event_types,
            unit=unit,  # type: ignore[arg-type]
            max_results=max_results,
            mode=mode,  # type: ignore[arg-type]
        )

    # ============== TIMELINE & EVENTS (2) ==============

    @mcp.tool()
    def get_timeline(individual_id: str) -> list[dict]:
        """
        Get chronological timeline of all life events for an individual.

        Returns events sorted by date, with events lacking dates at the end.
        Useful for building biographical narratives or understanding life progression.

        Args:
            individual_id: The GEDCOM ID (e.g., "I123" or "@I123@")

        Returns:
            List of events sorted chronologically, each with type, date, place, description
        """
        return _get_timeline(individual_id)

    @mcp.tool()
    def get_military_service() -> dict:
        """
        Find all individuals with military service across the tree.

        Scans all individuals' events for military indicators:
        - Event types: MILT, SERV
        - Keywords: war, military, army, navy, marine, soldier, regiment, etc.

        Useful for finding veterans, understanding family military history,
        or researching ancestors who served.

        Returns:
            Dictionary with:
            - result_count: Number of individuals with military service
            - individuals: List of individuals with their military events
            - time_periods: Counts grouped by century (1800s, 1900s, etc.)
            - service_locations: Top locations where service occurred
        """
        return _get_military_service()

    # ============== PLACE ANALYSIS (1) ==============

    @mcp.tool()
    def get_place_cluster(place: str, max_results: int = 100) -> dict:
        """
        Get all individuals connected to a location with event breakdown.

        Uses fuzzy place matching to find everyone with events at or near
        the specified location. Groups results by event type (births, deaths, etc.).

        Useful for understanding migration patterns, finding relatives in a region,
        or analyzing geographic concentrations.

        Args:
            place: Place name to search for (fuzzy matched)
            max_results: Maximum individuals to return (default 100)

        Returns:
            Dictionary with:
            - place: The search query
            - result_count: Number of individuals found
            - individuals: List of individuals with match scores
            - place_variants: Similar place spellings found in tree
            - event_breakdown: Counts by event type (BIRT, DEAT, RESI, etc.)
        """
        return _get_place_cluster(place, max_results)

    # ============== SURNAME ANALYSIS (1) ==============

    @mcp.tool()
    def get_surname_origins(surname: str) -> dict:
        """
        Analyze surname distribution and detect geographic origins.

        Extends surname lookup with origin detection by finding earliest
        births by location and tracking the surname's geographic spread over time.

        Useful for understanding where a family line originated and how it
        migrated across generations.

        Args:
            surname: Surname to analyze (case-insensitive)

        Returns:
            Dictionary with:
            - surname: The search query
            - count: Total individuals with this surname
            - individuals: List of all individuals
            - primary_origin: Place with earliest births (likely origin)
            - place_timeline: Place → [years] showing spread over time
            - statistics: earliest/latest birth, span, common places
        """
        return _get_surname_origins(surname)
