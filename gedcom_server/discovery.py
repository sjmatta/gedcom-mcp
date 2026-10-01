"""Progressive discovery with distinct read and proposal execution boundaries."""

from typing import Literal

from fastmcp.server.context import Context
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.tools.base import Tool, ToolAnnotations, ToolResult

CORE_READ_TOOLS = {
    "get_tree_context",
    "search_people",
    "get_people",
    "get_relatives",
    "get_relationship",
    "get_timeline",
    "get_record",
}
CORE_WRITE_TOOLS = {"prepare_change", "apply_tree_change", "maintain_tree"}
PREPARATIONS = {
    "create_person": "prepare_create_person",
    "update_person_name": "prepare_update_person_name",
    "edit_records": "prepare_record_changes",
    "restore": "prepare_tree_restore",
}
READ_HINTS = {"readOnlyHint": True, "destructiveHint": False}
PREPARE_HINTS = {"readOnlyHint": False, "destructiveHint": False}


class ResearchDiscovery(BM25SearchTransform):
    """Use FastMCP's authorized catalog and ranking, with bounded schema pages."""

    def __init__(self):
        super().__init__(
            always_visible=sorted(CORE_READ_TOOLS | CORE_WRITE_TOOLS),
            call_tool_name="call_research_tool",
            max_results=100,
        )

    def _make_search_tool(self) -> Tool:
        transform = self

        async def search_tools(
            query: str = "",
            category: Literal["research", "changes", "all"] = "research",
            offset: int = 0,
            limit: int = 3,
            ctx: Context = None,  # type: ignore[assignment]
        ) -> dict:
            """Discover specialized research or change-preparation tools and exact schemas.

            Use natural language or an exact tool name. Empty query browses the
            category. Follow next_offset with the same query/category. Research
            executes through call_research_tool; changes through prepare_change
            using the returned operation and full inputSchema as arguments.
            Applying changes and maintenance are explicit, separate core tools.
            """
            if offset < 0 or not 1 <= limit <= 10:
                raise ValueError("Use nonnegative offset and limit between 1 and 10")
            tools = await transform._get_visible_tools(ctx)
            tools = [
                t
                for t in tools
                if (
                    (
                        category in {"research", "all"}
                        and t.annotations
                        and t.annotations.read_only_hint
                    )
                    or (category in {"changes", "all"} and t.name in PREPARATIONS.values())
                )
            ]
            ranked = (
                await transform._search(tools, query)
                if query.strip()
                else sorted(tools, key=lambda t: t.name)
            )
            items = []
            for tool in ranked[offset : offset + limit]:
                item = tool.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)
                operation = next(
                    (op for op, name in PREPARATIONS.items() if name == tool.name), None
                )
                item["execution"] = (
                    {"tool": "prepare_change", "operation": operation}
                    if operation
                    else {"tool": "call_research_tool", "name": tool.name}
                )
                items.append(item)
            return {
                "query": query,
                "category": category,
                "total": len(ranked),
                "offset": offset,
                "next_offset": offset + limit if offset + limit < len(ranked) else None,
                "tools": items,
            }

        return Tool.from_function(
            search_tools,
            name="search_tools",
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
        )

    def _make_call_tool(self) -> Tool:
        async def call_research_tool(name: str, arguments: dict, ctx: Context) -> ToolResult:
            """Execute a discovered read-only research tool using its exact input schema.

            This entry point cannot prepare, apply, back up or export changes.
            Discover tools first with search_tools. Do not guess arguments.
            """
            catalog = await self.get_tool_catalog(ctx)
            tool = next((t for t in catalog if t.name == name), None)
            if not tool or not tool.annotations or tool.annotations.read_only_hint is not True:
                raise ValueError("Only available read-only research tools are allowed")
            if name in {"search_tools", "call_research_tool"}:
                raise ValueError("Discovery tools cannot execute each other")
            return await ctx.fastmcp.call_tool(name, arguments)

        return Tool.from_function(
            call_research_tool,
            name="call_research_tool",
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
        )


def register_prepare_tool(mcp):
    @mcp.tool(annotations=PREPARE_HINTS)
    async def prepare_change(
        operation: Literal["create_person", "update_person_name", "edit_records", "restore"],
        arguments: dict,
        ctx: Context,
    ) -> ToolResult:
        """Prepare a reviewed proposal; never changes the active family tree.

        Discover the operation's exact arguments with search_tools(category="changes").
        Supply expected_revision and reason inside arguments. edit_records supports
        atomic batches of sourced facts, person creation, names, family links,
        removals and merges. Read the complete diff before obtaining authorization
        and invoking apply_tree_change. Restore previews a whole prior revision.
        """
        name = PREPARATIONS[operation]
        # Normal FastMCP lookup/call preserves authorization, validation and middleware.
        return await ctx.fastmcp.call_tool(name, arguments)
