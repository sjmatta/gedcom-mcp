"""Smoke test the installed MCP stack through the actual stdio entry point."""

import asyncio
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

READ_TOOLS = {
    "audit_tree",
    "get_parent_families",
    "get_relationship_to_me",
    "get_home_person",
    "get_statistics",
    "get_individual",
    "get_biography",
    "get_family",
    "get_parents",
    "get_children",
    "get_spouses",
    "get_siblings",
    "get_ancestors",
    "get_descendants",
    "search_individuals",
    "get_relationship",
    "detect_pedigree_collapse",
    "traverse",
    "semantic_search",
    "search_nearby",
    "get_timeline",
    "get_military_service",
    "get_place_cluster",
    "get_surname_origins",
    "find_associates",
}

WRITE_TOOLS = {
    "plan_tree_prune",
    "get_tree_revision",
    "prepare_tree_change",
    "get_tree_change_diff",
    "apply_tree_change",
    "get_tree_history",
    "prepare_tree_restore",
    "backup_tree",
    "export_tree_revision",
}


def test_stdio_tools_and_resources():
    async def exercise_server():
        root = Path(__file__).resolve().parents[1]
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "gedcom_server", "--gedcom-file", str(root / "tests/fixtures/sample.ged")],
            cwd=str(root),
            env={
                "PHOENIX_ENABLED": "false",
                "GIS_SEARCH_ENABLED": "false",
                "SEMANTIC_SEARCH_ENABLED": "false",
                "GEDCOM_HOME_PERSON_ID": "",
                "GEDCOM_WRITES_ENABLED": "false",
            },
            keep_alive=False,
        )
        async with Client(transport, timeout=20) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert names >= READ_TOOLS
            assert "query" not in names
            assert names.isdisjoint(WRITE_TOOLS)
            result = await client.call_tool("get_statistics", {})
            assert not result.is_error
            assert result.data["total_individuals"] > 0
            resources = await client.list_resources()
            assert "gedcom://stats" in {str(resource.uri) for resource in resources}
            assert await client.read_resource("gedcom://stats")
            surnames = await client.read_resource("gedcom://surnames")
            assert surnames[0].text.splitlines() == ["smith: 4", "jones: 1", "williams: 1"]

    asyncio.run(asyncio.wait_for(exercise_server(), timeout=30))


def test_tool_descriptions_keep_full_docstring():
    """FastMCP 3+ truncates docstrings with an Args section to their first paragraph.

    Tools register through mcp_tools.tool(), which passes the whole docstring so
    Returns/Examples/usage notes still reach the model.
    """
    import inspect

    from gedcom_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert tools
    for tool in tools:
        assert tool.description == inspect.getdoc(tool.fn), tool.name


def test_opt_in_write_tools_prepare_apply_and_current_reads(tmp_path):
    async def exercise_server():
        root = Path(__file__).resolve().parents[1]
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "gedcom_server", "--gedcom-file", str(root / "tests/fixtures/sample.ged")],
            cwd=str(root),
            env={
                "PHOENIX_ENABLED": "false",
                "GIS_SEARCH_ENABLED": "false",
                "SEMANTIC_SEARCH_ENABLED": "false",
                "GEDCOM_HOME_PERSON_ID": "",
                "GEDCOM_WRITES_ENABLED": "true",
                "GEDCOM_STORE_DIR": str(tmp_path / "store"),
            },
            keep_alive=False,
        )
        async with Client(transport, timeout=20) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} >= WRITE_TOOLS
            status = await client.call_tool("get_tree_revision", {})
            assert status.data["revision"] == 0
            prepared = await client.call_tool(
                "prepare_tree_change",
                {
                    "expected_revision": 0,
                    "reason": "MCP transport verification",
                    "operations": [
                        {"op": "add_note", "record_id": "@I1@", "text": "MCP test note"}
                    ],
                },
            )
            assert not prepared.is_error
            assert "+1 NOTE MCP test note" in prepared.data["diff"]
            result = await client.call_tool(
                "apply_tree_change",
                {
                    "proposal_id": prepared.data["proposal_id"],
                    "expected_revision": 0,
                },
            )
            assert not result.is_error and result.data["revision"] == 1
            person = await client.call_tool("get_individual", {"individual_id": "@I1@"})
            assert "MCP test note" in person.data["notes"]
            resource = await client.read_resource("gedcom://individual/@I1@")
            assert "MCP test note" in resource[0].text
            restored = await client.call_tool(
                "prepare_tree_restore",
                {
                    "expected_revision": 1,
                    "restore_revision": 0,
                    "reason": "Undo transport test",
                },
            )
            result = await client.call_tool(
                "apply_tree_change",
                {
                    "proposal_id": restored.data["proposal_id"],
                    "expected_revision": 1,
                },
            )
            assert result.data["revision"] == 2

    asyncio.run(asyncio.wait_for(exercise_server(), timeout=45))
