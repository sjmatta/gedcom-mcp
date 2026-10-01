"""Research tools work through the public, read-only stdio MCP entry point."""

import asyncio
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def test_research_tools_stdio():
    async def exercise():
        root = Path(__file__).resolve().parents[1]
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "gedcom_server", "--gedcom-file", str(root / "tests/fixtures/sample.ged")],
            cwd=str(root),
            env={
                "PHOENIX_ENABLED": "false",
                "GIS_SEARCH_ENABLED": "false",
                "SEMANTIC_SEARCH_ENABLED": "false",
                "GEDCOM_WRITES_ENABLED": "false",
            },
            keep_alive=False,
        )
        async with Client(transport, timeout=20) as client:
            cases = [
                ("get_record", {"record_id": "I1", "limit": 2}),
                ("get_source", {"source_id": "S1"}),
                ("search_sources", {"query": "Census"}),
                ("get_source_references", {"source_id": "S1", "page": "Page 42"}),
                ("search_events", {"event_type": "MARR"}),
                ("get_timeline", {"individual_ids": ["I1", "I2"]}),
                ("get_people", {"individual_ids": ["I1", "missing"]}),
            ]
            results = {}
            for name, arguments in cases:
                result = await client.call_tool(
                    name
                    if name in {"get_record", "get_timeline", "get_people"}
                    else "call_research_tool",
                    arguments
                    if name in {"get_record", "get_timeline", "get_people"}
                    else {"name": name, "arguments": arguments},
                )
                assert not result.is_error, name
                results[name] = result.data
            page = results["get_record"]
            next_page = await client.call_tool(
                "get_record",
                {
                    "record_id": "I1",
                    "expected_snapshot": page["snapshot"],
                    "offset": page["next_offset"],
                    "limit": 2,
                },
            )
            assert next_page.data["snapshot"] == page["snapshot"]
            assert results["get_source"]["title"] == "Massachusetts Vital Records"
            assert results["search_sources"]["total"] == 1
            assert results["get_source_references"]["items"][0]["record_id"] == "@I1@"
            assert results["search_events"]["total"] == 2
            assert sum(e["type"] == "MARR" for e in results["get_timeline"]["items"]) == 1
            assert results["get_people"]["people"]["@missing@"] is None

    asyncio.run(asyncio.wait_for(exercise(), timeout=30))
