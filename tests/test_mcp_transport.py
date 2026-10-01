"""Exercise progressive discovery and reviewed edits through real stdio MCP."""

import asyncio
import inspect
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

from gedcom_server.discovery import CORE_READ_TOOLS, CORE_WRITE_TOOLS

READ_TOOLS = CORE_READ_TOOLS | {"search_tools", "call_research_tool"}
WRITE_TOOLS = CORE_WRITE_TOOLS


def transport(store=None):
    root = Path(__file__).resolve().parents[1]
    env = {
        "PHOENIX_ENABLED": "false",
        "GIS_SEARCH_ENABLED": "false",
        "SEMANTIC_SEARCH_ENABLED": "false",
        "GEDCOM_HOME_PERSON_ID": "",
        "GEDCOM_WRITES_ENABLED": "true" if store else "false",
    }
    if store:
        env["GEDCOM_STORE_DIR"] = str(store)
    return StdioTransport(
        command=sys.executable,
        args=["-m", "gedcom_server", "--gedcom-file", str(root / "tests/fixtures/sample.ged")],
        cwd=str(root),
        env=env,
        keep_alive=False,
    )


def test_stdio_tools_and_resources():
    async def exercise():
        async with Client(transport(), timeout=20) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == READ_TOOLS
            assert all(tool.annotations.read_only_hint for tool in tools)
            # Initial catalog remains compact; detailed edit schemas are deferred.
            assert len(json.dumps([tool.model_dump(mode="json") for tool in tools])) < 15000
            context = (await client.call_tool("get_tree_context", {})).data
            assert context["statistics"]["total_individuals"] > 0
            assert context["writes_enabled"] is False and context["revision"] is None
            person = (await client.call_tool("get_people", {})).data
            assert context["home_person"]["id"] in person["people"]
            search = (await client.call_tool("search_people", {"query": "Smith"})).data
            assert search["items"]
            assert (await client.call_tool("search_tools", {"category": "changes"})).data[
                "total"
            ] == 0
            offset = 0
            discovered = {}
            while offset is not None:
                page = (await client.call_tool("search_tools", {"offset": offset, "limit": 2})).data
                discovered.update({t["name"]: t for t in page["tools"]})
                offset = page["next_offset"]
            assert {
                "get_source",
                "search_events",
                "get_military_service",
                "audit_tree",
            } <= discovered.keys()
            assert all(
                t["inputSchema"] and t["execution"]["tool"] == "call_research_tool"
                for t in discovered.values()
            )
            result = await client.call_tool(
                "call_research_tool",
                {
                    "name": "get_source",
                    "arguments": {"source_id": "S1"},
                },
            )
            assert result.data["title"] == "Massachusetts Vital Records"
            assert not (await client.call_tool("search_tools", {"query": "zzzzunserved"})).data[
                "tools"
            ]
            for name in [
                "get_individual",
                "get_parents",
                "get_statistics",
                "get_group_timeline",
                "get_individuals_batch",
                "query",
            ]:
                with pytest.raises(Exception, match="Unknown tool"):
                    await client.call_tool(name, {})
            assert await client.read_resource("gedcom://stats")
            surnames = await client.read_resource("gedcom://surnames")
            assert surnames[0].text.splitlines() == ["smith: 4", "jones: 1", "williams: 1"]

    asyncio.run(asyncio.wait_for(exercise(), timeout=45))


def test_tool_descriptions_keep_full_docstring():
    from gedcom_server import mcp

    for tool in asyncio.run(mcp.list_tools()):
        assert tool.description == inspect.getdoc(tool.fn), tool.name


def test_opt_in_write_tools_prepare_apply_and_current_reads(tmp_path):
    async def exercise():
        async with Client(transport(tmp_path / "store"), timeout=20) as client:
            assert {t.name for t in await client.list_tools()} == READ_TOOLS | WRITE_TOOLS
            context = (await client.call_tool("get_tree_context", {})).data
            assert context["revision"] == 0 and context["writes_enabled"] is True
            definitions = (
                await client.call_tool("search_tools", {"category": "changes", "limit": 10})
            ).data
            assert definitions["total"] == 4
            for query, operation in [
                ("create a new person", "create_person"),
                ("correct a name", "update_person_name"),
                ("edit records", "edit_records"),
                ("restore earlier revision", "restore"),
            ]:
                ranked = (
                    await client.call_tool("search_tools", {"query": query, "category": "changes"})
                ).data
                assert ranked["tools"][0]["execution"]["operation"] == operation, query
            batch = next(
                t for t in definitions["tools"] if t["execution"]["operation"] == "edit_records"
            )
            assert "oneOf" in json.dumps(batch["inputSchema"])
            assert "update_name" in json.dumps(batch["inputSchema"])
            for name in [
                "apply_tree_change",
                "prepare_create_person",
                "prepare_change",
                "maintain_tree",
            ]:
                with pytest.raises(Exception, match="read-only"):
                    await client.call_tool("call_research_tool", {"name": name, "arguments": {}})
            for operation in ["apply_tree_change", "backup", "unknown"]:
                with pytest.raises(ToolError):
                    await client.call_tool(
                        "prepare_change", {"operation": operation, "arguments": {}}
                    )
            for ops in [
                [{"op": "add_note", "record_id": "@I1@", "text": "x", "typo": True}],
                [{"op": "delete_individual", "individual_id": "@I1@", "force": "true"}],
            ]:
                with pytest.raises(ToolError):
                    await client.call_tool(
                        "prepare_change",
                        {
                            "operation": "edit_records",
                            "arguments": {
                                "expected_revision": 0,
                                "reason": "Reject malformed inputs",
                                "operations": ops,
                            },
                        },
                    )
            created = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "create_person",
                        "arguments": {
                            "expected_revision": 0,
                            "reason": "Preview person",
                            "given_name": "Zoë",
                            "surname": "Example",
                            "sex": "U",
                        },
                    },
                )
            ).data
            new_id = created["individual_id"]
            assert "+1 NAME Zoë /Example/" in created["diff"]
            assert (await client.call_tool("get_people", {"individual_ids": [new_id]})).data[
                "people"
            ][new_id] is None
            assert (await client.call_tool("get_tree_context", {})).data["revision"] == 0
            applied = (
                await client.call_tool(
                    "apply_tree_change",
                    {
                        "proposal_id": created["proposal_id"],
                        "expected_revision": 0,
                    },
                )
            ).data
            assert applied["revision"] == 1
            assert (await client.call_tool("get_people", {"individual_ids": [new_id]})).data[
                "people"
            ][new_id]
            with pytest.raises(Exception, match="Tree changed"):
                await client.call_tool("get_people", {"expected_snapshot": context["snapshot"]})
            restored = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "restore",
                        "arguments": {
                            "expected_revision": 1,
                            "restore_revision": 0,
                            "reason": "Undo creation",
                        },
                    },
                )
            ).data
            await client.call_tool(
                "apply_tree_change",
                {"proposal_id": restored["proposal_id"], "expected_revision": 1},
            )
            noted = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "edit_records",
                        "arguments": {
                            "expected_revision": 2,
                            "reason": "Atomic linked creation and sourced fact",
                            "operations": [
                                {
                                    "op": "add_individual",
                                    "individual_id": "@NEW@",
                                    "name": "New /Person/",
                                },
                                {"op": "add_family", "family_id": "@NEWF@"},
                                {
                                    "op": "add_relationship",
                                    "family_id": "@NEWF@",
                                    "individual_id": "@NEW@",
                                    "role": "CHIL",
                                },
                                {
                                    "op": "add_event",
                                    "record_id": "@NEW@",
                                    "tag": "BIRT",
                                    "source_id": "@S1@",
                                    "date": "1900",
                                },
                                {"op": "add_note", "record_id": "@I1@", "text": "MCP test note"},
                            ],
                        },
                    },
                )
            ).data
            result = (
                await client.call_tool(
                    "apply_tree_change",
                    {"proposal_id": noted["proposal_id"], "expected_revision": 2},
                )
            ).data
            assert result["revision"] == 3
            person = (
                await client.call_tool("get_people", {"individual_ids": ["I1"], "view": "record"})
            ).data["people"]["@I1@"]
            assert "MCP test note" in person["notes"]
            new_person = (
                await client.call_tool("get_people", {"individual_ids": ["NEW"], "view": "record"})
            ).data["people"]["@NEW@"]
            assert new_person["sex"] is None
            assert new_person["events"][0]["citations"][0]["source_id"] == "@S1@"
            assert (
                "MCP test note" in (await client.read_resource("gedcom://individual/@I1@"))[0].text
            )
            renamed = (
                await client.call_tool(
                    "prepare_change",
                    {
                        "operation": "update_person_name",
                        "arguments": {
                            "expected_revision": 3,
                            "reason": "Correct structured name",
                            "individual_id": "@I1@",
                            "old_name": "John /SMITH/",
                            "name": "Jonathan /Smith/",
                            "given_name": "Jonathan",
                            "surname": "Smith",
                        },
                    },
                )
            ).data
            assert "+2 GIVN Jonathan" in renamed["diff"]
            await client.call_tool(
                "apply_tree_change", {"proposal_id": renamed["proposal_id"], "expected_revision": 3}
            )
            person = (
                await client.call_tool("get_people", {"individual_ids": ["I1"], "view": "record"})
            ).data["people"]["@I1@"]
            assert person["given_name"] == "Jonathan" and person["surname"] == "Smith"
            history = (
                await client.call_tool(
                    "call_research_tool", {"name": "get_tree_history", "arguments": {}}
                )
            ).data
            assert len(history) == 5
            export = (
                await client.call_tool("maintain_tree", {"action": "export", "revision": 4})
            ).data
            assert Path(export["path"]).read_bytes()
            backup = (await client.call_tool("maintain_tree", {"action": "backup"})).data
            assert backup

    asyncio.run(asyncio.wait_for(exercise(), timeout=60))
