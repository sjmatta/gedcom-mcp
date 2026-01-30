"""Natural language query tool using Strands Agents SDK."""

import os
from collections.abc import Generator
from typing import Any

from dotenv import load_dotenv
from strands import Agent, tool
from strands.models import AnthropicModel

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


# Wrap existing functions as Strands tools
@tool
def get_home_person() -> dict | None:
    """Get the home person (tree owner) - the primary person in the tree.

    Use this as a starting point when the user asks about 'my' ancestry
    or doesn't specify a person.
    """
    return _get_home_person()


@tool
def get_biography(individual_id: str) -> dict | None:
    """Get comprehensive biographical information for a person.

    Includes vital dates, parents, spouses, children, events, and notes.
    Use this when you need full details about someone.

    Args:
        individual_id: GEDCOM ID (e.g., '@I123@' or 'I123')
    """
    return _get_biography(individual_id)


@tool
def get_ancestors(individual_id: str, generations: int = 4) -> dict:
    """Get the ancestor tree for a person up to N generations.

    Returns a nested structure with father/mother branches.

    Args:
        individual_id: GEDCOM ID (e.g., '@I123@' or 'I123')
        generations: Number of generations (default 4, max 10)
    """
    return _get_ancestors(individual_id, generations)


@tool
def get_descendants(individual_id: str, generations: int = 4) -> dict:
    """Get the descendant tree for a person up to N generations.

    Args:
        individual_id: GEDCOM ID (e.g., '@I123@' or 'I123')
        generations: Number of generations (default 4, max 10)
    """
    return _get_descendants(individual_id, generations)


@tool
def get_relationship(id1: str, id2: str) -> dict:
    """Calculate how two individuals are related.

    Returns relationships like: parent, child, sibling, first cousin once removed, etc.

    Args:
        id1: GEDCOM ID of first person
        id2: GEDCOM ID of second person
    """
    return _get_relationship(id1, id2)


@tool
def get_surname_group(surname: str, include_spouses: bool = False) -> dict:
    """Get all individuals with a particular surname plus statistics.

    Args:
        surname: Surname to search for (case-insensitive)
        include_spouses: Include spouses who married into the surname
    """
    return _get_surname_group(surname, include_spouses)


@tool
def search_individuals(name: str, max_results: int = 50) -> list[dict]:
    """Search for individuals by name.

    Use this when you need to find someone by name (partial match on given name or surname).

    Args:
        name: Name to search for (case-insensitive partial match)
        max_results: Maximum results to return (default 50)
    """
    return _search_individuals(name, max_results)


@tool
def get_statistics() -> dict:
    """Get overall statistics about the family tree.

    Returns total individuals, families, date ranges, top surnames, etc.
    """
    return _get_statistics()


TOOLS = [
    get_home_person,
    get_biography,
    get_ancestors,
    get_descendants,
    get_relationship,
    get_surname_group,
    search_individuals,
    get_statistics,
]

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


def _create_agent(callback_handler: Any = None) -> Agent:
    """Create a Strands agent with genealogy tools.

    Args:
        callback_handler: Optional callback for streaming events.
            If None, uses the default PrintingCallbackHandler.
    """
    model = AnthropicModel(
        model_id=os.getenv("GEDCOM_QUERY_MODEL", DEFAULT_MODEL),
        max_tokens=int(os.getenv("GEDCOM_QUERY_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
    )
    return Agent(
        model=model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        callback_handler=callback_handler,
    )


def _query_with_callback(question: str) -> Generator[str, None, None]:
    """Answer a natural language question with callback-based streaming.

    Uses a callback handler to capture streaming text as it's generated.
    This provides a sync generator interface over the Strands callback system.

    Args:
        question: Natural language question about the genealogy data

    Yields:
        Text chunks as they stream from the agent
    """
    chunks: list[str] = []

    def collect_callback(**kwargs: Any) -> None:
        if "data" in kwargs:
            chunks.append(kwargs["data"])

    agent = _create_agent(callback_handler=collect_callback)
    agent(question)

    yield from chunks


def _query_sync(question: str) -> str:
    """Answer a natural language question about the family tree (synchronous).

    This is the primary interface for MCP tools. Uses the Strands Agent's
    synchronous invocation pattern and returns the final text response.

    Args:
        question: Natural language question about the genealogy data

    Returns:
        Prose answer to the question
    """
    # Use null callback to suppress printing
    agent = _create_agent(callback_handler=None)
    result = agent(question)

    # Extract text from the result message (Message is a TypedDict)
    message = result.message
    if message and message.get("content"):
        text_parts = []
        for block in message["content"]:
            # ContentBlock is a union type, check for text key
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        return "".join(text_parts)

    return "Unable to generate a response."


# For backwards compatibility, _query is an alias for the sync version
_query = _query_sync
