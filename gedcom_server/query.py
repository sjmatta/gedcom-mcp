"""Natural language query tool using an internal LLM agent."""

import json
import os
from typing import Any

import litellm
from dotenv import load_dotenv

from .core import (
    _get_ancestors,
    _get_descendants,
    _get_home_person,
    _get_relationship,
    _get_statistics,
    _get_surname_group,
    _search_individuals,
)
from .narrative import _get_biography

# Load .env file if present
load_dotenv()

# Configuration
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096

# Tool definitions for the internal agent
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_home_person",
            "description": "Get the home person (tree owner) - the primary person in the tree. "
            "Use this as a starting point when the user asks about 'my' ancestry or doesn't "
            "specify a person.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_biography",
            "description": "Get comprehensive biographical information for a person including "
            "vital dates, parents, spouses, children, events, and notes. Use this when you "
            "need full details about someone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "individual_id": {
                        "type": "string",
                        "description": "GEDCOM ID (e.g., '@I123@' or 'I123')",
                    }
                },
                "required": ["individual_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ancestors",
            "description": "Get the ancestor tree for a person up to N generations. Returns a "
            "nested structure with father/mother branches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "individual_id": {
                        "type": "string",
                        "description": "GEDCOM ID (e.g., '@I123@' or 'I123')",
                    },
                    "generations": {
                        "type": "integer",
                        "description": "Number of generations (default 4, max 10)",
                        "default": 4,
                    },
                },
                "required": ["individual_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_descendants",
            "description": "Get the descendant tree for a person up to N generations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "individual_id": {
                        "type": "string",
                        "description": "GEDCOM ID (e.g., '@I123@' or 'I123')",
                    },
                    "generations": {
                        "type": "integer",
                        "description": "Number of generations (default 4, max 10)",
                        "default": 4,
                    },
                },
                "required": ["individual_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relationship",
            "description": "Calculate how two individuals are related (e.g., parent, sibling, "
            "first cousin once removed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id1": {
                        "type": "string",
                        "description": "GEDCOM ID of first person",
                    },
                    "id2": {
                        "type": "string",
                        "description": "GEDCOM ID of second person",
                    },
                },
                "required": ["id1", "id2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_surname_group",
            "description": "Get all individuals with a particular surname plus statistics about "
            "the family group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "surname": {
                        "type": "string",
                        "description": "Surname to search for (case-insensitive)",
                    },
                    "include_spouses": {
                        "type": "boolean",
                        "description": "Include spouses who married into the surname",
                        "default": False,
                    },
                },
                "required": ["surname"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_individuals",
            "description": "Search for individuals by name (partial match on given name or "
            "surname). Use this when you need to find someone by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name to search for (case-insensitive partial match)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 50)",
                        "default": 50,
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_statistics",
            "description": "Get overall statistics about the family tree (total individuals, "
            "families, date ranges, top surnames).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Mapping from tool names to actual functions
TOOL_FUNCTIONS: dict[str, Any] = {
    "get_home_person": _get_home_person,
    "get_biography": _get_biography,
    "get_ancestors": _get_ancestors,
    "get_descendants": _get_descendants,
    "get_relationship": _get_relationship,
    "get_surname_group": _get_surname_group,
    "search_individuals": _search_individuals,
    "get_statistics": _get_statistics,
}

SYSTEM_PROMPT = """You are a genealogy research assistant with access to a family tree database.
Your job is to answer questions about the family tree by using the available tools.

IMPORTANT: Always start by calling get_home_person first. The home person is the tree owner and
should be used as the default reference point for all queries. When the user says "my", "I", or
asks about ancestry without specifying a person, they mean the home person. Even for general
questions, having the home person context helps you provide better answers.

Tool usage guidelines:
- get_home_person: ALWAYS call this first to establish context
- search_individuals: Find people by name when a specific person is mentioned
- get_biography: Get full details about a person (dates, places, family, events)
- get_ancestors: Trace ancestry back through generations
- get_descendants: See a person's children and grandchildren
- get_relationship: Determine how two people are related
- get_surname_group: Explore everyone with a particular last name
- get_statistics: Get overview of the entire tree

When answering:
- Be concise but thorough
- Include relevant dates and places when available
- For ancestor questions, clearly explain the lineage (e.g., "Your paternal grandmother was...")
- For relationship questions, explain the connection clearly

If you cannot find the requested information, say so clearly."""


def _execute_tool(tool_name: str, arguments: dict) -> Any:
    """Execute a tool function with the given arguments."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return func(**arguments)
    except Exception as e:
        return {"error": str(e)}


def _extract_text_response(response: Any) -> str:
    """Extract text content from a LiteLLM response."""
    if hasattr(response, "choices") and response.choices:
        message = response.choices[0].message
        if hasattr(message, "content") and message.content:
            return message.content
    return ""


def _query(question: str) -> str:
    """Answer a natural language question about the family tree.

    Uses an internal LLM agent with access to genealogy tools to investigate
    and synthesize an answer.

    Args:
        question: Natural language question about the genealogy data

    Returns:
        Prose answer to the question
    """
    model = os.getenv("GEDCOM_QUERY_MODEL", DEFAULT_MODEL)
    max_tokens = int(os.getenv("GEDCOM_QUERY_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    max_iterations = int(os.getenv("GEDCOM_QUERY_MAX_ITERATIONS", "10"))

    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(max_iterations):
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
            )
        except Exception as e:
            return f"Error communicating with LLM: {e}"

        if not response.choices:
            return "No response from LLM"

        choice = response.choices[0]
        message = choice.message

        # Check if we're done (no tool calls)
        if choice.finish_reason == "stop" or not getattr(message, "tool_calls", None):
            return _extract_text_response(response) or "Unable to generate a response."

        # Process tool calls
        assistant_message: dict = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_message)

        # Execute each tool call and add results
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            result = _execute_tool(tool_name, arguments)
            result_str = json.dumps(result, default=str) if result is not None else "null"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
            )

    return "Reached maximum iterations without completing the query."
