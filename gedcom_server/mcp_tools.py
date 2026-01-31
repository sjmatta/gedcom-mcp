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
    _search_individuals,
    _traverse,
)
from .narrative import _get_biography
from .query import _query
from .semantic import _semantic_search


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
