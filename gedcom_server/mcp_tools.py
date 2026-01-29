"""MCP tool definitions for the GEDCOM genealogy server."""

from .core import (
    _detect_pedigree_collapse,
    _find_common_ancestors,
    _get_ancestors,
    _get_children,
    _get_descendants,
    _get_family,
    _get_home_person,
    _get_individual,
    _get_individuals_batch,
    _get_parents,
    _get_relationship,
    _get_relationship_matrix,
    _get_siblings,
    _get_spouses,
    _get_statistics,
    _get_surname_group,
    _search_by_birth,
    _search_by_place,
    _search_individuals,
)
from .events import (
    _get_citations,
    _get_events,
    _get_events_batch,
    _get_family_events,
    _get_family_timeline,
    _get_notes,
    _get_timeline,
    _search_events,
)
from .narrative import (
    _get_biographies_batch,
    _get_biography,
    _get_repositories,
    _search_narrative,
)
from .places import (
    _fuzzy_search_place,
    _geocode_place,
    _get_all_places,
    _get_place,
    _get_place_variants,
    _search_nearby,
    _search_similar_places,
)
from .sources import _get_source, _get_sources, _search_sources


def register_tools(mcp):
    """Register all MCP tools with the server."""

    @mcp.tool()
    def get_home_person() -> dict | None:
        """
        Get the home person (tree owner) - Stephen John Matta (1984).

        This is a convenience function to quickly access the primary person in the tree.

        Returns:
            Full individual record for the home person
        """
        return _get_home_person()

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

    @mcp.tool()
    def get_individual(individual_id: str) -> dict | None:
        """
        Get full details for an individual by their GEDCOM ID.

        Args:
            individual_id: The GEDCOM ID (e.g., "I123" or "@I123@")

        Returns:
            Full individual record or None if not found
        """
        return _get_individual(individual_id)

    @mcp.tool()
    def get_family(family_id: str) -> dict | None:
        """
        Get family information by GEDCOM family ID.

        Args:
            family_id: The GEDCOM family ID (e.g., "F123" or "@F123@")

        Returns:
            Family record with husband, wife, children IDs and marriage info
        """
        return _get_family(family_id)

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
    def get_ancestors(individual_id: str, generations: int = 4) -> dict:
        """
        Get ancestor tree up to N generations.

        Args:
            individual_id: The GEDCOM ID of the individual
            generations: Number of generations to retrieve (default 4, max 10)

        Returns:
            Nested dictionary representing the ancestor tree
        """
        return _get_ancestors(individual_id, generations)

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

    # ============== RELATIONSHIP ANALYSIS TOOLS ==============

    @mcp.tool()
    def get_individuals_batch(individual_ids: list[str]) -> dict[str, dict | None]:
        """
        Get multiple individuals efficiently in one call.

        Useful for batch operations when you need data for many individuals at once.

        Args:
            individual_ids: List of GEDCOM IDs to retrieve (e.g., ["I123", "I456"])

        Returns:
            Dict mapping each ID to its individual data (or None if not found)
        """
        return _get_individuals_batch(individual_ids)

    @mcp.tool()
    def find_common_ancestors(id1: str, id2: str, max_generations: int = 10) -> dict:
        """
        Find common ancestors between two individuals.

        Useful for determining "how are these two people related?" by finding
        shared ancestry points.

        Args:
            id1: GEDCOM ID of first individual
            id2: GEDCOM ID of second individual
            max_generations: Max generations to search (default 10)

        Returns:
            Dict with both individuals' info and list of common ancestors,
            each showing generation distance from both sides
        """
        return _find_common_ancestors(id1, id2, max_generations)

    @mcp.tool()
    def get_relationship(id1: str, id2: str) -> dict:
        """
        Calculate and name the relationship between two individuals.

        Returns relationships like: parent, child, sibling, half-sibling, spouse,
        grandparent, grandchild, aunt/uncle, niece/nephew, first cousin,
        second cousin once removed, etc.

        Args:
            id1: GEDCOM ID of first individual
            id2: GEDCOM ID of second individual

        Returns:
            Dict with both individuals' info, relationship name, and
            common ancestor info for cousin relationships
        """
        return _get_relationship(id1, id2)

    @mcp.tool()
    def detect_pedigree_collapse(individual_id: str, max_generations: int = 10) -> dict:
        """
        Detect pedigree collapse (ancestors appearing multiple times).

        Pedigree collapse occurs when ancestors appear multiple times in a family
        tree, typically due to cousin marriages or other intermarriage within
        a community.

        Args:
            individual_id: GEDCOM ID of the individual
            max_generations: Max generations to search (default 10)

        Returns:
            Dict with individual info and list of collapse points showing
            which ancestors appear multiple times and through which paths
        """
        return _detect_pedigree_collapse(individual_id, max_generations)

    @mcp.tool()
    def search_by_birth(
        year: int | None = None,
        place: str | None = None,
        year_range: int = 5,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Search individuals by birth year and/or place.

        Args:
            year: Birth year to search for
            place: Birth place to search for (partial match)
            year_range: Years to search around the given year (default 5)
            max_results: Maximum number of results (default 50)

        Returns:
            List of matching individuals
        """
        return _search_by_birth(year, place, year_range, max_results)

    @mcp.tool()
    def search_by_place(place: str, max_results: int = 50) -> list[dict]:
        """
        Search individuals by any place (birth, death, or residence).

        Args:
            place: Place name to search for (partial match, case-insensitive)
            max_results: Maximum number of results (default 50)

        Returns:
            List of matching individuals with place context
        """
        return _search_by_place(place, max_results)

    # ============== FUZZY PLACE SEARCH TOOLS ==============

    @mcp.tool()
    def fuzzy_search_place(place: str, threshold: int = 70, max_results: int = 50) -> list[dict]:
        """
        Search for individuals by place with fuzzy matching.

        Handles typos, abbreviations, spelling variations, and historical name changes.
        Uses multiple matching strategies:
        - Exact substring matching
        - Abbreviation expansion (St. -> Saint, N.Y. -> New York)
        - Fuzzy string matching (typo tolerance)
        - Phonetic matching (similar pronunciation)
        - Historical name variants (Constantinople -> Istanbul)

        Args:
            place: Place name to search (tolerates typos and variations)
            threshold: Minimum similarity score 0-100 (default 70)
            max_results: Maximum results to return

        Returns:
            List of individuals with match info including score
        """
        return _fuzzy_search_place(place, threshold, max_results)

    @mcp.tool()
    def search_similar_places(place: str, max_results: int = 20) -> list[dict]:
        """
        Find places in the tree similar to the given name.

        Useful for discovering spelling variations, typos, or related locations.
        Combines fuzzy string matching and phonetic analysis.

        Args:
            place: Place name to find similar matches for
            max_results: Maximum results to return

        Returns:
            List of similar places with similarity scores and match type
        """
        return _search_similar_places(place, max_results)

    @mcp.tool()
    def get_place_variants(place: str) -> list[dict]:
        """
        Get all variant spellings/forms of a place found in the tree.

        Groups places that normalize to the same form or match phonetically.
        Example: "New York" might return ["New York", "N.Y.", "NYC", "New York City"]

        Args:
            place: Place name to find variants for

        Returns:
            List of variant places with match type (normalized, phonetic, or fuzzy)
        """
        return _get_place_variants(place)

    @mcp.tool()
    def get_all_places(max_results: int = 500) -> list[dict]:
        """
        Get all unique places in the genealogy tree.

        Returns:
            List of place summaries (id, original, normalized)
        """
        return _get_all_places(max_results)

    @mcp.tool()
    def get_place(place_id: str) -> dict | None:
        """
        Get a place by its ID.

        Args:
            place_id: The place ID (hash of normalized form)

        Returns:
            Full place record with components and coordinates, or None
        """
        return _get_place(place_id)

    @mcp.tool()
    def geocode_place(place: str) -> dict | None:
        """
        Get geographic coordinates for a place name.

        Uses offline GeoNames data for geocoding.

        Args:
            place: Place name to geocode

        Returns:
            Dict with latitude, longitude, and source, or None if not found
        """
        return _geocode_place(place)

    @mcp.tool()
    def search_nearby(
        place: str,
        radius_km: float = 50,
        event_types: list[str] | None = None,
        max_results: int = 100,
    ) -> list[dict]:
        """
        Find individuals with events within a radius of a place.

        Performs spatial search using geographic coordinates.
        Note: Only places that can be geocoded will be included.

        Args:
            place: Reference place name (will be geocoded)
            radius_km: Search radius in kilometers (default 50)
            event_types: Filter by event types (BIRT, DEAT, RESI, etc.)
            max_results: Maximum results to return

        Returns:
            List of individuals with distance info, sorted by distance
        """
        return _search_nearby(place, radius_km, event_types, max_results)

    @mcp.tool()
    def get_statistics() -> dict:
        """
        Get statistics about the genealogy tree.

        Returns:
            Dictionary with counts, date ranges, and other statistics
        """
        return _get_statistics()

    # ============== SOURCE TOOLS ==============

    @mcp.tool()
    def get_sources(max_results: int = 100) -> list[dict]:
        """
        Get all sources in the genealogy tree.

        Args:
            max_results: Maximum number of sources to return (default 100)

        Returns:
            List of source summaries (id, title, author)
        """
        return _get_sources(max_results)

    @mcp.tool()
    def get_source(source_id: str) -> dict | None:
        """
        Get full details for a source by its GEDCOM ID.

        Args:
            source_id: The GEDCOM source ID (e.g., "S123" or "@S123@")

        Returns:
            Full source record or None if not found
        """
        return _get_source(source_id)

    @mcp.tool()
    def search_sources(query: str, max_results: int = 50) -> list[dict]:
        """
        Search sources by title or author.

        Args:
            query: Search term (case-insensitive partial match)
            max_results: Maximum number of results (default 50)

        Returns:
            List of matching source summaries
        """
        return _search_sources(query, max_results)

    # ============== EVENT TOOLS ==============

    @mcp.tool()
    def get_events(individual_id: str) -> list[dict]:
        """
        Get all life events for an individual.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of events (birth, death, residence, occupation, etc.)
        """
        return _get_events(individual_id)

    @mcp.tool()
    def search_events(
        event_type: str | None = None,
        place: str | None = None,
        year: int | None = None,
        year_range: int = 5,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Search events by type, place, and/or year.

        Args:
            event_type: Event type to filter by (BIRT, DEAT, RESI, OCCU, etc.)
            place: Place name to search for (partial match)
            year: Year to search for
            year_range: Years around the given year to include (default 5)
            max_results: Maximum number of results (default 50)

        Returns:
            List of matching events with individual info
        """
        return _search_events(event_type, place, year, year_range, max_results)

    @mcp.tool()
    def get_citations(individual_id: str) -> list[dict]:
        """
        Get all source citations for an individual across all events.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of citations with source and event context
        """
        return _get_citations(individual_id)

    @mcp.tool()
    def get_notes(individual_id: str) -> list[dict]:
        """
        Get all notes for an individual across all events.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of notes with event context
        """
        return _get_notes(individual_id)

    @mcp.tool()
    def get_timeline(individual_id: str) -> list[dict]:
        """
        Get chronological timeline of events for an individual.

        Args:
            individual_id: The GEDCOM ID of the individual

        Returns:
            List of events sorted by date (earliest first)
        """
        return _get_timeline(individual_id)

    @mcp.tool()
    def get_family_events(family_id: str) -> list[dict]:
        """
        Get all events for an entire family unit (spouses + children).

        Returns a chronological timeline of all events for the husband, wife,
        and all children in the family. Useful for seeing how a family's
        lives unfolded together.

        Args:
            family_id: GEDCOM family ID (e.g., "F123" or "@F123@")

        Returns:
            List of events with individual context, sorted chronologically
        """
        return _get_family_events(family_id)

    @mcp.tool()
    def get_family_timeline(
        individual_ids: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[dict]:
        """
        Create merged timeline across multiple individuals.

        Useful for seeing how multiple people's lives overlapped and intersected.
        For example, see events for all siblings, or grandparents and grandchildren.

        Args:
            individual_ids: List of GEDCOM IDs to include
            start_year: Optional filter for earliest year
            end_year: Optional filter for latest year

        Returns:
            List of events with individual context, sorted chronologically
        """
        return _get_family_timeline(individual_ids, start_year, end_year)

    # ============== NARRATIVE TOOLS ==============

    @mcp.tool()
    def get_biography(individual_id: str) -> dict | None:
        """
        Get a comprehensive narrative package for one person.

        This is the ideal tool for building a complete understanding of someone's life
        in ONE call. Returns everything needed for biographical narrative:

        - vital_summary: Quick "Born X. Died Y." summary
        - birth/death: Full date and place info
        - parents/spouses/children: Family names (not IDs) for easy narrative use
        - events: All life events with full citation details including URLs
        - notes: All biographical notes (obituaries, baptism records, directory entries, etc.)

        Args:
            individual_id: The GEDCOM ID of the individual (e.g., "I123" or "@I123@")

        Returns:
            Complete biography dict or None if not found
        """
        return _get_biography(individual_id)

    @mcp.tool()
    def search_narrative(query: str, max_results: int = 50) -> dict:
        """
        Full-text search across all narrative content in the tree.

        Searches:
        - Individual-level notes (obituaries, stories, census extracts, directory entries)
        - Event-level notes
        - Citation text fields

        Perfect for queries like:
        - "Find all obituaries" -> search_narrative("obituary")
        - "Who worked at the steel mill?" -> search_narrative("steel mill")
        - "Find baptism records" -> search_narrative("baptism")

        Args:
            query: Text to search for (case-insensitive)
            max_results: Maximum results to return (default 50)

        Returns:
            Dict with query, result_count, and list of matches with snippets
        """
        return _search_narrative(query, max_results)

    @mcp.tool()
    def get_repositories() -> list[dict]:
        """
        Get all source repositories in the tree.

        Repositories are where sources come from (e.g., Ancestry.com, Family History Library).

        Returns:
            List of repository records with id, name, address, and url
        """
        return _get_repositories()

    # ============== BULK OPERATION TOOLS ==============

    @mcp.tool()
    def get_events_batch(individual_ids: list[str]) -> dict[str, list[dict]]:
        """
        Get events for multiple individuals in one call.

        Reduces API round-trips when you need events for a group of people
        (e.g., all siblings, a family reunion group, DNA matches).

        Args:
            individual_ids: List of GEDCOM IDs (e.g., ["I123", "I456", "I789"])

        Returns:
            Dict mapping each ID → list of events (empty list if not found)
        """
        return _get_events_batch(individual_ids)

    @mcp.tool()
    def get_biographies_batch(individual_ids: list[str]) -> dict[str, dict | None]:
        """
        Get full biographies for multiple individuals in one call.

        Each biography includes vital summary, family context with names,
        all events with citations, and notes. This is the most comprehensive
        bulk data retrieval tool.

        Args:
            individual_ids: List of GEDCOM IDs (e.g., ["I123", "I456", "I789"])

        Returns:
            Dict mapping each ID → full biography dict (or None if not found)
        """
        return _get_biographies_batch(individual_ids)

    @mcp.tool()
    def get_surname_group(surname: str, include_spouses: bool = False) -> dict:
        """
        Get all individuals with a surname plus summary statistics.

        Returns everyone with the surname in ONE call, avoiding the need
        to search then individually fetch each person. Also computes
        statistics about the surname group.

        Args:
            surname: Surname to look up (case-insensitive)
            include_spouses: If True, also include spouses who married into the surname

        Returns:
            Dict with:
            - surname: The searched surname
            - count: Number of individuals with this surname
            - individuals: List of individual summaries
            - statistics: Earliest/latest birth years, common places, generation estimate
        """
        return _get_surname_group(surname, include_spouses)

    @mcp.tool()
    def get_relationship_matrix(individual_ids: list[str]) -> dict:
        """
        Calculate all pairwise relationships for a group of individuals.

        Given N people, efficiently computes all N×(N-1)/2 relationships.
        Useful for family reunion planning, DNA match analysis, or understanding
        how a group of people relate to each other.

        Example: For 5 people, calculates 10 relationship pairs in one call
        instead of requiring 10 separate get_relationship calls.

        Args:
            individual_ids: List of GEDCOM IDs to analyze

        Returns:
            Dict with:
            - individuals: List of {id, name} for valid IDs
            - relationships: List of {id1, id2, relationship} pairs
            - pair_count: Total number of pairs calculated
        """
        return _get_relationship_matrix(individual_ids)
