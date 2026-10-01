"""Evidence, lineage, bounds and discovery behavior for the major-release surface."""

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.transforms import Visibility

from gedcom_server import mcp, state
from gedcom_server.discovery import READ_HINTS, ResearchDiscovery
from gedcom_server.interface_reads import get_people, get_relatives, search_people
from gedcom_server.models import Family, Individual, ParentFamily


@pytest.fixture
def qualified_tree(monkeypatch):
    people = {
        "@C@": Individual(
            "@C@",
            "Child",
            family_as_child="@B@",
            parent_families=[
                ParentFamily("@B@", "birth"),
                ParentFamily("@A@", "adopted"),
                ParentFamily("@X@", "birth", "disproven"),
            ],
        ),
        "@P@": Individual(
            "@P@",
            "Birth parent",
            families_as_spouse=["@B@"],
            family_as_child="@G@",
            parent_families=[ParentFamily("@G@", "birth")],
        ),
        "@AD@": Individual("@AD@", "Adoptive parent", families_as_spouse=["@A@"]),
        "@NO@": Individual("@NO@", "Disproven parent", families_as_spouse=["@X@"]),
        "@G@": Individual("@G@", "Grandparent", families_as_spouse=["@G@"]),
        "@S@": Individual(
            "@S@", "Sibling", family_as_child="@B@", parent_families=[ParentFamily("@B@", "birth")]
        ),
    }
    families = {
        "@B@": Family("@B@", husband_id="@P@", children_ids=["@C@", "@S@"]),
        "@A@": Family("@A@", wife_id="@AD@", children_ids=["@C@"]),
        "@X@": Family("@X@", husband_id="@NO@", children_ids=["@C@"]),
        "@G@": Family("@G@", husband_id="@G@", children_ids=["@P@"]),
    }
    monkeypatch.setattr(state, "individuals", people)
    monkeypatch.setattr(state, "families", families)
    monkeypatch.setattr(state, "HOME_PERSON_ID", "@C@")
    return people, families


def test_navigation_retains_all_assertions_but_traverses_selected_lineage(qualified_tree):
    for lineage, expected in [
        ("default", {"@P@"}),
        ("birth", {"@P@"}),
        ("adopted", {"@AD@"}),
        ("all", {"@P@", "@AD@"}),
    ]:
        result = get_relatives("C", "parents", lineage=lineage)
        assert {p["id"] for p in result["items"]} == expected
        assert len(result["parent_families"]["parent_families"]) == 3
        assert all(p["path"][0]["family_id"] for p in result["items"])
    assert get_relatives("AD", "children")["items"] == []
    assert get_relatives("AD", "children", lineage="adopted")["items"][0]["id"] == "@C@"
    assert get_relatives("NO", "children", lineage="all")["items"] == []
    assert get_relatives("C", "siblings")["items"][0]["id"] == "@S@"


def test_terminal_ancestors_distinguish_depth_boundary_from_end_of_line(qualified_tree):
    shallow = get_relatives("C", "ancestors", 1, "terminal")
    assert shallow["items"] == [] and shallow["depth_limited"]
    deep = get_relatives("C", "ancestors", 2, "terminal")
    assert [p["id"] for p in deep["items"]] == ["@G@"]
    assert deep["items"][0]["level"] == 2 and not deep["depth_limited"]
    assert deep["items"][0]["path"][1]["pedigree"] == "birth"


def test_cycles_are_bounded_and_tree_references_are_marked(qualified_tree):
    people, families = qualified_tree
    people["@G@"].family_as_child = "@B@"
    people["@G@"].parent_families = [ParentFamily("@B@", "birth")]
    families["@B@"].children_ids.append("@G@")
    flat = get_relatives("C", "ancestors", 20)
    assert len(flat["items"]) == 2
    tree = get_relatives("C", "ancestors", 20, "tree")["tree"]
    assert tree["relatives"][0]["person"]["relatives"][0]["person"]["relatives"][0]["person"][
        "repeated_reference"
    ]


def test_navigation_budgets_and_inputs_are_explicit(qualified_tree, monkeypatch):
    with pytest.raises(ValueError, match="generations"):
        get_relatives("C", "ancestors", 21)
    with pytest.raises(ValueError, match="terminal"):
        get_relatives("C", "spouses", view="terminal")
    with pytest.raises(ValueError, match="not found"):
        get_relatives("missing", "children")
    monkeypatch.setattr("gedcom_server.interface_reads.MAX_TREE_NODES", 1)
    for view in ["list", "tree"]:
        with pytest.raises(ValueError, match="node budget"):
            get_relatives("C", "ancestors", 2, view)


def test_people_views_missing_ids_duplicates_and_snapshot_validation():
    result = get_people(["I1", "@I1@", "missing"], "record")
    assert set(result["people"]) == {"@I1@", "@missing@"}
    assert result["people"]["@missing@"] is None
    assert result["people"]["@I1@"]["events"]
    assert get_people(["I1"], "biography")["people"]["@I1@"]["events"]
    with pytest.raises(ValueError, match="at most 20"):
        get_people(["I1"] * 21, "biography")
    with pytest.raises(ValueError, match="Tree changed"):
        get_people(["I1"], expected_snapshot="stale")
    with pytest.raises(ValueError, match="limit"):
        search_people("Smith", limit=0)


def test_relationship_algorithms_and_explicit_reference(qualified_tree):
    async def exercise():
        async with Client(mcp) as client:
            result = (
                await client.call_tool(
                    "get_relationship",
                    {
                        "individual_id": "C",
                        "reference_id": "AD",
                        "method": "path",
                        "lineage": "adopted",
                    },
                )
            ).data
            assert result["relationship"].startswith("child")
            assert result["path"][0]["pedigree"] == "adopted"
            with pytest.raises(Exception, match="requires method=path"):
                await client.call_tool(
                    "get_relationship", {"individual_id": "C", "lineage": "adopted"}
                )

    asyncio.run(exercise())


def test_discovery_and_dispatch_respect_visibility_and_read_boundary():
    server = FastMCP("Filtered research")

    @server.tool(annotations=READ_HINTS)
    def public_read() -> dict:
        """Read public evidence."""
        return {"ok": True}

    @server.tool(annotations=READ_HINTS)
    def secret_read() -> dict:
        """Read hidden evidence."""
        raise AssertionError("Filtered operation executed")

    @server.tool(annotations={"readOnlyHint": False})
    def edit_record() -> dict:
        raise AssertionError("Mutation executed through read proxy")

    server.add_transform(Visibility(False, names={"secret_read"}))
    server.add_transform(ResearchDiscovery())

    async def exercise():
        async with Client(server) as client:
            discovery = (await client.call_tool("search_tools", {"category": "all"})).data
            assert [t["name"] for t in discovery["tools"]] == ["public_read"]
            assert (
                await client.call_tool(
                    "call_research_tool", {"name": "public_read", "arguments": {}}
                )
            ).data == {"ok": True}
            for name in ["secret_read", "edit_record", "call_research_tool", "search_tools"]:
                with pytest.raises(ToolError):
                    await client.call_tool("call_research_tool", {"name": name, "arguments": {}})

    asyncio.run(exercise())


def test_discovery_and_execution_across_stateless_http_requests():
    from starlette.testclient import TestClient

    app = mcp.http_app(
        path="/mcp", stateless_http=True, json_response=True, host_origin_protection=False
    )
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    with TestClient(app) as client:

        def request(id_, method, params):
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params},
                headers=headers,
            )
            assert response.status_code == 200
            return response.json()["result"]

        catalog = request(1, "tools/list", {})
        assert len(catalog["tools"]) == 9
        found = request(
            2,
            "tools/call",
            {
                "name": "search_tools",
                "arguments": {
                    "query": "source citations",
                    "limit": 3,
                },
            },
        )
        assert not found.get("isError")
        schemas = found["structuredContent"]["tools"]
        assert "get_source_references" in [t["name"] for t in schemas]
        result = request(
            3,
            "tools/call",
            {
                "name": "call_research_tool",
                "arguments": {
                    "name": "get_source_references",
                    "arguments": {"source_id": "S1"},
                },
            },
        )
        assert not result.get("isError")
        assert result["structuredContent"]["total"] > 0


def test_relatives_pagination_retains_same_evidence_and_snapshot(qualified_tree):
    first = get_relatives("C", "parents", lineage="all", limit=1)
    second = get_relatives(
        "C",
        "parents",
        lineage="all",
        offset=first["next_offset"],
        limit=1,
        expected_snapshot=first["snapshot"],
    )
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert second["next_offset"] is None
    assert second["items"][0]["path"][0]["pedigree"] == "adopted"
    with pytest.raises(ValueError, match="Tree changed"):
        get_relatives("C", "parents", expected_snapshot="stale")
    with pytest.raises(ValueError, match="pagination offset"):
        get_relatives("C", "parents", view="tree", offset=1)


def test_discovery_ranks_intended_research_workflows_first():
    async def exercise():
        async with Client(mcp) as client:
            cases = [
                ("inspect source citations", "get_source_references"),
                ("military service", "get_military_service"),
                ("people near Pittsburgh", "search_nearby"),
                ("pedigree collapse", "detect_pedigree_collapse"),
                ("surname origins", "get_surname_origins"),
            ]
            for query, expected in cases:
                result = (await client.call_tool("search_tools", {"query": query})).data
                assert result["tools"][0]["name"] == expected, query
                assert result["tools"][0]["inputSchema"]

    asyncio.run(exercise())
