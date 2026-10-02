"""Consolidated, task-oriented MCP reads and discoverable research tools."""

import inspect
from typing import Literal

from .associates import _find_associates
from .core import _detect_pedigree_collapse, _get_family, _get_relationship, _get_surname_origins
from .discovery import READ_HINTS
from .events import _get_military_service
from .interface_reads import Relation, snapshot_metadata, tree_context
from .interface_reads import get_people as read_people
from .interface_reads import get_relatives as read_relatives
from .interface_reads import search_people as find_people
from .places import _get_place_cluster
from .relationships import Lineage, _get_relationship_to_me
from .spatial import _search_nearby
from .state import synchronized
from .telemetry import traced_tool


def register_tools(mcp):
    def tool(fn):
        return mcp.tool(description=inspect.getdoc(fn), annotations=READ_HINTS)(synchronized(fn))

    @tool
    def get_tree_context() -> dict:
        """Orient research: home person, tree statistics, snapshot, revision and capability status.

        Start here for "my family" questions and before preparing edits. Disabled
        capabilities are reported explicitly. Specialized tools are discovered
        through search_tools; mutations use the separate prepare/review/apply flow.
        """
        return tree_context()

    @tool
    def search_people(
        query: str,
        mode: Literal["name", "semantic"] = "name",
        limit: int = 50,
        expected_snapshot: str | None = None,
    ) -> dict:
        """Find people by partial name or natural-language evidence, returning usable IDs.

        Name matching is deterministic. Semantic mode requires enabled local search;
        its ranked results are candidates, not proof. Verify evidence with person,
        record, event and source reads. limit is 1–100. Preserve names, dates and
        negation when trying query paraphrases; retain the original query.
        """
        return find_people(query, mode, limit, expected_snapshot)

    @tool
    def get_people(
        individual_ids: list[str] | None = None,
        view: Literal["summary", "record", "biography"] = "summary",
        expected_snapshot: str | None = None,
    ) -> dict:
        """Read one or several people in a consistent snapshot; omitted IDs select home person.

        summary gives compact names/vitals (up to 500 IDs); record includes parsed
        events, notes and family IDs (100); biography includes narrative context,
        relatives, citations and family events (20). Missing IDs map to null;
        duplicate normalized IDs collapse. get_record preserves complete original
        evidence, alternate facts, unknown fields and exact field paths.
        """
        return read_people(individual_ids, view, expected_snapshot)

    @tool
    def get_relatives(
        individual_id: str,
        relation: Relation,
        generations: int = 1,
        view: Literal["list", "tree", "terminal"] = "list",
        lineage: Lineage = "default",
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
        max_nodes: int = 1000,
    ) -> dict:
        """Navigate parents, children, spouses, siblings, ancestors or descendants with link evidence.

        generations bounds repeated traversal: parents/ancestors 0–20, others 0–10.
        list returns unique people with one shortest path; tree retains repeated
        references; terminal finds known end-of-line ancestors within the limit.
        list/terminal paginate with offset/limit (1–500); reuse expected_snapshot.
        max_nodes (1–50000, default 1000) bounds work; exceeding it raises an
        explicit error, never a false terminal ancestor. tree requires offset=0.
        depth_limited means further recorded links exist beyond the requested depth.
        default selects unambiguous parent families; all includes all usable links;
        birth/adopted/foster/sealing require explicit matching qualifiers. Disproven
        links are excluded. All root parent families, including ambiguous/disproven
        assertions, remain visible. Pedigree does not prove genetic parentage.
        """
        return read_relatives(
            individual_id,
            relation,
            generations,
            view,
            lineage,
            expected_snapshot,
            offset,
            limit,
            max_nodes,
        )

    @tool
    def get_relationship(
        individual_id: str,
        reference_id: str | None = None,
        method: Literal["kinship", "path"] = "kinship",
        max_generations: int | None = 10,
        lineage: Lineage = "default",
        max_steps: int = 30,
        expected_snapshot: str | None = None,
    ) -> dict:
        """Explain person 1 relative to a reference person; omitted reference selects home person.

        kinship uses selected families and common ancestors (generation limit;
        null searches up to 100), with detailed cousin/sibling labels. path searches
        one shortest recorded family connection with pedigree evidence (max_steps
        1–100), supporting explicit lineage and relatives by marriage. These are
        distinct algorithms; paths do not enumerate every possible relationship.
        Nondefault lineage is supported only by path. No genetic relationship is proven.
        """
        from . import state

        reference = reference_id or state.HOME_PERSON_ID
        if not reference:
            raise ValueError("Provide reference_id or configure a home person")
        meta = snapshot_metadata(expected_snapshot)
        if method == "path":
            result = _get_relationship_to_me(individual_id, lineage, max_steps, reference)
            if "home_person" in result:
                result["reference_person"] = result.pop("home_person")
        elif lineage != "default":
            raise ValueError("Explicit lineage requires method=path")
        else:
            result = _get_relationship(individual_id, reference, max_generations)
        return {**meta, "method": method, **result}

    @tool
    def get_timeline(
        individual_ids: list[str],
        start_year: int | None = None,
        end_year: int | None = None,
        include_undated: bool = False,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Read an evidence timeline for one person or up to 500 selected people.

        Includes personal and spouse-family events, shared family events once,
        original dates, notes, citations and owning record paths. Year matching
        uses inclusive interval overlap; approximate dates retain their recorded
        nominal year. Unknown/calendar dates pass year filters only when requested.
        Follow next_offset with the returned snapshot as expected_snapshot.
        """
        from .research_reads import get_group_timeline

        return get_group_timeline(
            individual_ids, start_year, end_year, include_undated, expected_snapshot, offset, limit
        )

    @tool
    def list_records(
        record_type: str | None = None,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Find all GEDCOM record IDs, including sources, repositories, media and shared notes.

        Optional record_type is an exact GEDCOM tag (e.g. REPO or OBJE). Includes
        unreferenced records and HEAD/TRLR metadata. Read each with get_record for
        exact field paths and subtree hashes before editing. Follow next_offset
        with the returned snapshot as expected_snapshot. limit is 1–500.
        """
        from .research_reads import list_records as read

        return read(record_type, expected_snapshot, offset, limit)

    @tool
    def get_record(
        record_id: str,
        path: list[dict] | None = None,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Read original GEDCOM fields, including alternate facts and unknown tags.

        Optional path selects a subtree using tag and zero-based sibling index,
        e.g. [{"tag": "BIRT", "index": 1}]. Each field returns its absolute path
        within the record, original text, logical continuation text (up to 2000
        UTF-8 bytes, with text_truncated), and
        subtree_sha256 for guarded update/replace/remove operations. Use HEAD or
        TRLR for document metadata, or anonymous-TAG-index for other anonymous
        records. Results are paginated by lines;
        concatenate raw across pages for the complete record or subtree.
        Pass returned snapshot as expected_snapshot on subsequent pages.
        Missing records/paths raise errors. Current UTF-8 GEDCOM only.
        """
        from .research_reads import get_record as read

        return read(record_id, path, expected_snapshot, offset, limit)

    @tool
    def get_source(source_id: str) -> dict | None:
        """Read source metadata and its repository. Missing sources return null.

        Use get_record for complete original source/repository fields, and
        get_source_references to find the facts citing this source.
        """
        from .research_reads import get_source as read

        return read(source_id)

    @tool
    def search_sources(
        query: str,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Search source title, author, publication and note by case-insensitive substring.

        Empty query lists sources. Follow next_offset and pass the returned
        snapshot as expected_snapshot to avoid mixing tree versions.
        """
        from .research_reads import search_sources as read

        return read(query, expected_snapshot, offset, limit)

    @tool
    def get_source_references(
        source_id: str,
        page: str | None = None,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Find all original citations pointing to a source, across every record type.

        Returns owning record, exact citation and fact paths, original citation
        fields/text, including page, notes, quality and exporter extensions.
        Optional page matches PAGE text exactly. Sharing a source does not imply
        sharing a document or household. Missing sources raise errors.
        Follow next_offset with returned snapshot as expected_snapshot.
        """
        from .research_reads import get_source_references as read

        return read(source_id, page, expected_snapshot, offset, limit)

    @tool
    def search_events(
        event_type: str | None = None,
        place: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        individual_ids: list[str] | None = None,
        include_undated: bool = False,
        expected_snapshot: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Search individual and family events with their original evidence fields.

        Type is a GEDCOM tag; place uses case-insensitive substring matching.
        Year filters use inclusive interval overlap, retaining original dates.
        BEF/AFT and FROM/TO are open intervals at year precision; ABT/CAL/EST
        use the nominal recorded year without inventing an uncertainty window.
        Unknown dates and non-European calendar dates pass year filters only
        with include_undated=true. Without year filters all dates are included.
        Optional individual_ids scopes a branch/group selected using get_relatives
        selections (max 500); includes family events for their recorded spouses.
        No inferred events or participants. Follow next_offset with snapshot.
        """
        from .research_reads import search_events as read

        return read(
            event_type,
            place,
            start_year,
            end_year,
            individual_ids,
            include_undated,
            expected_snapshot,
            offset,
            limit,
        )

    @tool
    def audit_tree(expected_revision: int | None = None, offset: int = 0, limit: int = 100) -> dict:
        """Scan the entire tree for structural errors and evidence-review warnings.

        Checks all pointer tags (including extensions), reciprocal family links,
        duplicate memberships, self-parenting, ancestry cycles, conflicting vital
        facts and uncited vital events. Reports connected components. This does not
        establish historical truth or fully validate the GEDCOM standard.
        Findings are paginated; follow next_offset with the returned revision as
        expected_revision to prevent mixing revisions. No tree changes occur.
        """
        from .tree_audit import audit_tree as run_audit

        return run_audit(expected_revision, offset, limit)

    @tool
    @traced_tool
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

    @tool
    @traced_tool
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

    @tool
    @traced_tool
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

    @tool
    @traced_tool
    def get_military_service() -> dict:
        """
        Find explicit military records and possible military references across the tree.

        Scans all individuals' events for military indicators:
        - Event types: MILT, SERV
        - Contextual military phrases in descriptions and notes

        Each matching event includes military_evidence: explicit_tag or
        possible_reference. A prose reference does not prove the person served.

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

    @tool
    @traced_tool
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

    @tool
    @traced_tool
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

    @tool
    @traced_tool
    def find_associates(
        individual_id: str,
        place: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        exclude_relatives: bool = True,
        max_results: int = 50,
    ) -> dict:
        """
        Find likely neighbors and associates based on time+place overlap.

        Implements the genealogist's FAN Club technique (Friends, Associates, Neighbors)
        to discover people who overlap in time AND place but are NOT known relatives.
        Useful for finding witnesses, godparents, business partners, or migration companions.

        Scoring factors:
        - Same place + same year: highest score
        - Same place + within 5 years: moderate score
        - Lifespan overlap: bonus up to 30%
        - Multiple matching places: bonus per additional place

        Args:
            individual_id: GEDCOM ID of the focal individual (e.g., "I123" or "@I123@")
            place: Optional - filter to specific location (fuzzy matched)
            start_year: Optional - filter time range start
            end_year: Optional - filter time range end
            exclude_relatives: Filter out blood/marriage relatives (default True)
            max_results: Limit results (default 50, max 200)

        Returns:
            Dictionary with:
            - individual: The focal person's info
            - filters_applied: Active filters
            - result_count: Number of associates found
            - associates: List sorted by association_strength (0.0-1.0) with:
              - id, name, birth_date, death_date
              - association_strength: Overall score
              - overlapping_events: Where/when paths crossed
              - lifespan_overlap_years: Years alive at same time
              - is_relative: Whether related (when exclude_relatives=False)
            - computation_stats: Performance metrics

        Examples:
            find_associates("@I123@")  # All associates
            find_associates("@I123@", place="Pittsburgh")  # Only Pittsburgh connections
            find_associates("@I123@", start_year=1880, end_year=1920)  # Time-bounded
            find_associates("@I123@", exclude_relatives=False)  # Include relatives
        """
        return _find_associates(
            individual_id=individual_id,
            place=place,
            start_year=start_year,
            end_year=end_year,
            exclude_relatives=exclude_relatives,
            max_results=max_results,
        )
