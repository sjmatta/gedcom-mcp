# API Reference

Complete reference for all 24 MCP tools and 4 resources provided by the GEDCOM MCP Server.

## Table of Contents

- [Context Tools (2)](#context-tools)
- [Lookup Tools (3)](#lookup-tools)
- [Navigation Tools (6)](#navigation-tools)
- [Search Tools (3)](#search-tools)
- [Relationship Tools (3)](#relationship-tools)
- [Timeline & Events (2)](#timeline--events)
- [Place & Surname Analysis (2)](#place--surname-analysis)
- [Natural Language (1)](#natural-language)
- [MCP Resources (4)](#mcp-resources)

---

## Context Tools

### get_home_person()

Get the home person (tree owner).

This is the essential starting point for "my ancestors" queries. Use this first to establish context for genealogy exploration.

**Returns:**
- Full individual record for the home person

**Example:**
```json
{
  "id": "@I123@",
  "name": "Stephen John Matta",
  "birth_date": "1984",
  "birth_place": "Pittsburgh, Pennsylvania",
  ...
}
```

---

### get_statistics()

Get statistics about the genealogy tree.

Provides tree overview and orientation: total individuals, families, date ranges, gender breakdown, and top surnames.

**Returns:**
- Dictionary with counts, date ranges, and other statistics

**Example:**
```json
{
  "total_individuals": 1523,
  "total_families": 487,
  "earliest_birth": "1720",
  "latest_birth": "2020",
  "top_surnames": [
    {"surname": "Smith", "count": 45},
    {"surname": "Jones", "count": 32}
  ]
}
```

---

## Lookup Tools

### get_individual(individual_id: str)

Get basic details for an individual by their GEDCOM ID.

Lightweight lookup - returns basic record with family link IDs. Use `get_biography()` when you need full context (events, notes, sources).

**Parameters:**
- `individual_id` (str): The GEDCOM ID (e.g., "I123" or "@I123@")

**Returns:**
- Individual record with name, dates, places, and family IDs

**Example:**
```json
{
  "id": "@I123@",
  "full_name": "John Smith",
  "birth_date": "1850",
  "birth_place": "New York",
  "death_date": "1920",
  "family_as_child": "@F45@",
  "families_as_spouse": ["@F67@"]
}
```

---

### get_biography(individual_id: str)

Get comprehensive narrative package for one person.

Heavy/full context - returns everything needed for biographical narrative:
- vital_summary: Quick "Born X. Died Y." summary
- birth/death: Full date and place info
- parents/spouses/children: Family names (not IDs) for easy narrative use
- events: All life events with full citation details including URLs
- notes: All biographical notes (obituaries, baptism records, etc.)

Use `get_individual()` for lightweight scanning of many people. Use this when diving deep into one person.

**Parameters:**
- `individual_id` (str): The GEDCOM ID (e.g., "I123" or "@I123@")

**Returns:**
- Complete biography dictionary or None if not found

**Example:**
```json
{
  "id": "@I123@",
  "name": "John Smith",
  "vital_summary": "Born 1850 in New York. Died 1920 in Pennsylvania.",
  "parents": ["Mary Smith", "James Smith"],
  "spouses": ["Jane Doe"],
  "children": ["William Smith", "Sarah Smith"],
  "events": [
    {
      "type": "BIRT",
      "date": "1850",
      "place": "New York",
      "citations": [...]
    }
  ],
  "notes": ["Obituary text..."]
}
```

---

### get_family(family_id: str)

Get family unit information by GEDCOM family ID.

Returns the family record with husband, wife, and children.

**Parameters:**
- `family_id` (str): The GEDCOM family ID (e.g., "F123" or "@F123@")

**Returns:**
- Family record with husband, wife, children IDs and marriage info

**Example:**
```json
{
  "id": "@F123@",
  "husband_id": "@I100@",
  "wife_id": "@I101@",
  "children_ids": ["@I200@", "@I201@"],
  "marriage_date": "1875",
  "marriage_place": "Philadelphia"
}
```

---

## Navigation Tools

### get_parents(individual_id: str)

Get the parents of an individual.

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual

**Returns:**
- Dictionary with father and mother info, or None if not found

**Example:**
```json
{
  "individual": {"id": "@I123@", "name": "John Smith"},
  "father": {"id": "@I100@", "name": "James Smith"},
  "mother": {"id": "@I101@", "name": "Mary Smith"}
}
```

---

### get_children(individual_id: str)

Get all children of an individual (from all marriages/partnerships).

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual

**Returns:**
- List of children with summary info

**Example:**
```json
[
  {
    "id": "@I200@",
    "name": "William Smith",
    "birth_date": "1880"
  },
  {
    "id": "@I201@",
    "name": "Sarah Smith",
    "birth_date": "1882"
  }
]
```

---

### get_spouses(individual_id: str)

Get all spouses/partners of an individual.

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual

**Returns:**
- List of spouses with summary info and marriage details

**Example:**
```json
[
  {
    "id": "@I150@",
    "name": "Jane Doe",
    "marriage_date": "1875",
    "marriage_place": "Philadelphia"
  }
]
```

---

### get_siblings(individual_id: str)

Get siblings of an individual (same parents).

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual

**Returns:**
- List of siblings with summary info

**Example:**
```json
[
  {
    "id": "@I124@",
    "name": "Mary Smith",
    "birth_date": "1852"
  }
]
```

---

### get_ancestors(individual_id: str, generations: int = 4, filter: str | None = None)

Get ancestor tree up to N generations.

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual
- `generations` (int): Number of generations to retrieve (default 4, max 20)
- `filter` (str | None): Optional filter:
  - `None`: Return full nested tree (default)
  - `"terminal"`: Return only end-of-line ancestors (brick walls/oldest known)

**Returns:**
- If filter is None: Nested dictionary representing the ancestor tree
- If filter is "terminal": List of terminal ancestors with generation and path

**Examples:**
```python
get_ancestors("@I123@", 4)  # Standard 4-generation tree
get_ancestors("@I123@", 20, "terminal")  # Find oldest known ancestors
```

---

### get_descendants(individual_id: str, generations: int = 4)

Get descendant tree up to N generations.

**Parameters:**
- `individual_id` (str): The GEDCOM ID of the individual
- `generations` (int): Number of generations to retrieve (default 4, max 10)

**Returns:**
- Nested dictionary representing the descendant tree

---

### traverse(individual_id: str, direction: str, depth: int = 1)

Generic graph traversal for advanced/custom navigation.

Use this when you need multi-level traversal beyond what the specific navigation tools provide. Performs breadth-first traversal.

**Parameters:**
- `individual_id` (str): Starting person's GEDCOM ID
- `direction` (str): "parents" | "children" | "spouses" | "siblings"
- `depth` (int): How many levels to traverse (default 1, max 10)

**Returns:**
- List of individuals found, each with a "level" field indicating depth

**Examples:**
```python
traverse("@I123@", "children", 2)  # Children and grandchildren
traverse("@I123@", "parents", 3)   # Parents, grandparents, great-grandparents
traverse("@I123@", "siblings", 1)  # Just siblings
```

---

## Search Tools

### search_individuals(name: str, max_results: int = 50)

Search for individuals by name (partial match on given name or surname).

**Parameters:**
- `name` (str): Name to search for (case-insensitive partial match)
- `max_results` (int): Maximum number of results to return (default 50)

**Returns:**
- List of matching individuals with summary info

**Example:**
```json
[
  {
    "id": "@I123@",
    "name": "John Smith",
    "birth_date": "1850",
    "death_date": "1920"
  }
]
```

---

### semantic_search(query: str, max_results: int = 20)

Search for individuals using natural language semantic matching.

Finds people based on meaning, not keywords. Works best for conceptual queries that traditional text search would miss.

**Requires:** `SEMANTIC_SEARCH_ENABLED=true` environment variable

**Parameters:**
- `query` (str): Natural language description of what you're looking for
- `max_results` (int): Max results to return (default 20, max 100)

**Returns:**
- Dictionary with query, result_count, and results list containing individual_id, name, birth_date, death_date, relevance_score, and snippet

**Examples:**
```python
semantic_search("served in Civil War")
semantic_search("emigrated from Ireland")
semantic_search("died in childbirth")
semantic_search("coal miners in Pennsylvania")
semantic_search("farmers in Scotland")
```

---

### search_nearby(location: str, radius_miles: float = 50, event_types: list[str] | None = None, unit: str = "miles", max_results: int = 100, mode: str = "proximity")

Find individuals with events near or within a location.

Supports two search modes:
- **"proximity"** (default): Find people within X miles of a point
- **"within"**: Find people with events inside a region's bounding box

**Parameters:**
- `location` (str): Place name to search around (fuzzy matched)
- `radius_miles` (float): Search radius (default 50, max 500) - ignored when mode="within"
- `event_types` (list[str] | None): Optional filter - list of event types like ["BIRT", "DEAT", "MARR"]
- `unit` (str): Distance unit - "miles" (default) or "km"
- `max_results` (int): Maximum results to return (default 100)
- `mode` (str): Search mode - "proximity" (default) or "within"
  - proximity: Find people within X miles of the location's center point
  - within: Find people with events inside the location's bounding box

**Returns:**
- Dictionary with:
  - reference_location: matched place with coordinates/bbox and confidence
  - mode: the search mode used ("proximity" or "within")
  - search_radius_miles: the search radius (proximity mode only)
  - geocoding_status: "running", "complete", or "disabled"
  - coverage: how many places were successfully geocoded
  - result_count: number of matches found
  - results: list of individuals with distance (proximity) or matching events

**Examples:**
```python
search_nearby("Pittsburgh", 50)  # Within 50 miles of Pittsburgh
search_nearby("Benkovce", 25, ["BIRT"])  # Births within 25 miles
search_nearby("New York", mode="within")  # Everyone inside NY State
search_nearby("California", mode="within", event_types=["BIRT"])  # Births in CA
```

---

## Relationship Tools

### get_relationship(id1: str, id2: str, max_generations: int | None = 10)

Calculate and name the relationship between two individuals.

Detects these relationship types:
- Direct lineage: parent, grandparent, great-grandparent, 2nd great-grandparent, etc. (unlimited depth)
- Direct descendants: child, grandchild, great-grandchild, etc.
- Siblings: sibling, half-sibling
- Extended: spouse, aunt/uncle, niece/nephew
- Cousins: first cousin, second cousin once removed, etc.

**Parameters:**
- `id1` (str): GEDCOM ID of first individual
- `id2` (str): GEDCOM ID of second individual
- `max_generations` (int | None): How far back to search for common ancestors. Pass null/None for unlimited depth (searches up to 100 generations).

**Returns:**
- Dict with both individuals' info, relationship name, and common ancestor info for cousin relationships

**Examples:**
```python
get_relationship("@I123@", "@I456@")  # Default 10-generation search
get_relationship("@I123@", "@I456@", None)  # Unlimited search depth
```

---

### detect_pedigree_collapse(individual_id: str, max_generations: int = 10)

Detect pedigree collapse (ancestors appearing multiple times).

Pedigree collapse occurs when ancestors appear multiple times in a family tree, typically due to cousin marriages or other intermarriage within a community. This is a discovery feature for finding interesting patterns.

**Parameters:**
- `individual_id` (str): GEDCOM ID of the individual
- `max_generations` (int): Max generations to search (default 10)

**Returns:**
- Dict with individual info and list of collapse points showing which ancestors appear multiple times and through which paths

---

### find_associates(individual_id: str, place: str | None = None, start_year: int | None = None, end_year: int | None = None, exclude_relatives: bool = True, max_results: int = 50)

Find likely neighbors and associates based on time+place overlap.

Implements the genealogist's FAN Club technique (Friends, Associates, Neighbors) to discover people who overlap in time AND place but are NOT known relatives. Useful for finding witnesses, godparents, business partners, or migration companions.

**Scoring factors:**
- Same place + same year: highest score
- Same place + within 5 years: moderate score
- Lifespan overlap: bonus up to 30%
- Multiple matching places: bonus per additional place

**Parameters:**
- `individual_id` (str): GEDCOM ID of the focal individual (e.g., "I123" or "@I123@")
- `place` (str | None): Optional - filter to specific location (fuzzy matched)
- `start_year` (int | None): Optional - filter time range start
- `end_year` (int | None): Optional - filter time range end
- `exclude_relatives` (bool): Filter out blood/marriage relatives (default True)
- `max_results` (int): Limit results (default 50, max 200)

**Returns:**
- Dictionary with:
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

**Examples:**
```python
find_associates("@I123@")  # All associates
find_associates("@I123@", place="Pittsburgh")  # Only Pittsburgh connections
find_associates("@I123@", start_year=1880, end_year=1920)  # Time-bounded
find_associates("@I123@", exclude_relatives=False)  # Include relatives
```

---

## Timeline & Events

### get_timeline(individual_id: str)

Get chronological timeline of all life events for an individual.

Returns events sorted by date, with events lacking dates at the end. Useful for building biographical narratives or understanding life progression.

**Parameters:**
- `individual_id` (str): The GEDCOM ID (e.g., "I123" or "@I123@")

**Returns:**
- List of events sorted chronologically, each with type, date, place, description

**Example:**
```json
[
  {
    "type": "BIRT",
    "date": "1850",
    "place": "New York",
    "description": null
  },
  {
    "type": "MARR",
    "date": "1875",
    "place": "Philadelphia",
    "description": null
  },
  {
    "type": "DEAT",
    "date": "1920",
    "place": "Pennsylvania",
    "description": null
  }
]
```

---

### get_military_service()

Find all individuals with military service across the tree.

Scans all individuals' events for military indicators:
- Event types: MILT, SERV
- Keywords: war, military, army, navy, marine, soldier, regiment, etc.

Useful for finding veterans, understanding family military history, or researching ancestors who served.

**Returns:**
- Dictionary with:
  - result_count: Number of individuals with military service
  - individuals: List of individuals with their military events
  - time_periods: Counts grouped by century (1800s, 1900s, etc.)
  - service_locations: Top locations where service occurred

---

## Place & Surname Analysis

### get_place_cluster(place: str, max_results: int = 100)

Get all individuals connected to a location with event breakdown.

Uses fuzzy place matching to find everyone with events at or near the specified location. Groups results by event type (births, deaths, etc.).

Useful for understanding migration patterns, finding relatives in a region, or analyzing geographic concentrations.

**Parameters:**
- `place` (str): Place name to search for (fuzzy matched)
- `max_results` (int): Maximum individuals to return (default 100)

**Returns:**
- Dictionary with:
  - place: The search query
  - result_count: Number of individuals found
  - individuals: List of individuals with match scores
  - place_variants: Similar place spellings found in tree
  - event_breakdown: Counts by event type (BIRT, DEAT, RESI, etc.)

---

### get_surname_origins(surname: str)

Analyze surname distribution and detect geographic origins.

Extends surname lookup with origin detection by finding earliest births by location and tracking the surname's geographic spread over time.

Useful for understanding where a family line originated and how it migrated across generations.

**Parameters:**
- `surname` (str): Surname to analyze (case-insensitive)

**Returns:**
- Dictionary with:
  - surname: The search query
  - count: Total individuals with this surname
  - individuals: List of all individuals
  - primary_origin: Place with earliest births (likely origin)
  - place_timeline: Place → [years] showing spread over time
  - statistics: earliest/latest birth, span, common places

---

## Natural Language

### query(question: str)

Answer a natural language question about the family tree.

**IMPORTANT:** This tool is a FALLBACK for MCP clients that lack subagent capabilities. If your client supports spawning subagents/subtasks, use those instead - they will be more capable and have access to your full toolset. This tool runs a simple internal reasoning loop that is less powerful than a proper subagent.

**Use this tool ONLY when:**
- Your MCP client does not support subagents
- You need to investigate genealogy data without filling context with intermediate tool calls

For simple lookups or when you need structured data, use the individual tools (`get_biography`, `get_ancestors`, etc.) instead.

**Requires:** `ANTHROPIC_API_KEY` environment variable

**Parameters:**
- `question` (str): Natural language question about the genealogy data

**Returns:**
- Prose answer to the question

**Examples:**
```python
query("Who are Stephen's maternal grandparents?")
query("Trace my ancestry back 4 generations and summarize")
query("How are @I123@ and @I456@ related?")
query("What do we know about everyone named Smith?")
query("Create a narrative of my family history")
```

---

## MCP Resources

In addition to tools, the server provides 4 MCP resources for direct data access:

### gedcom://individual/{id}

Get individual record by GEDCOM ID.

**Example:** `gedcom://individual/@I123@`

Returns the complete individual record including all events, notes, and family links.

---

### gedcom://family/{id}

Get family record by GEDCOM family ID.

**Example:** `gedcom://family/@F123@`

Returns the complete family record including spouses, children, and marriage information.

---

### gedcom://stats

Get tree statistics.

**Example:** `gedcom://stats`

Returns comprehensive statistics about the genealogy tree including counts, date ranges, and surname distribution.

---

### gedcom://surnames

Get all surnames with counts.

**Example:** `gedcom://surnames`

Returns a list of all surnames in the tree with the count of individuals for each surname, sorted by frequency.

---

## Common Event Types

When using tools that filter by event type (like `search_nearby`), these are common GEDCOM event types:

- `BIRT` - Birth
- `DEAT` - Death
- `MARR` - Marriage
- `RESI` - Residence
- `OCCU` - Occupation
- `IMMI` - Immigration
- `EMIG` - Emigration
- `BURI` - Burial
- `BAPM` - Baptism
- `CHR` - Christening
- `MILT` - Military service
- `SERV` - General service
- `EVEN` - Generic event

For a complete list, consult the GEDCOM 5.5.1 specification.
