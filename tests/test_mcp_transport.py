"""Smoke test the installed MCP stack through the actual stdio entry point."""

import asyncio
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


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
            },
            keep_alive=False,
        )
        async with Client(transport, timeout=20) as client:
            tools = await client.list_tools()
            assert len(tools) == 25
            assert "get_statistics" in {tool.name for tool in tools}
            result = await client.call_tool("get_statistics", {})
            assert not result.is_error
            assert result.data["total_individuals"] > 0
            resources = await client.list_resources()
            assert "gedcom://stats" in {str(resource.uri) for resource in resources}
            assert await client.read_resource("gedcom://stats")

    asyncio.run(asyncio.wait_for(exercise_server(), timeout=30))


def test_tool_descriptions_keep_full_docstring():
    """FastMCP 3+ truncates docstrings with an Args section to their first paragraph.

    Tools register through mcp_tools.tool(), which passes the whole docstring so
    Returns/Examples/usage notes still reach the model.
    """
    import inspect

    from gedcom_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 25
    for tool in tools:
        assert tool.description == inspect.getdoc(tool.fn), tool.name
