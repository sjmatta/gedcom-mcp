"""Replaceable GEDCOM editing boundary.

Storage and tools exchange immutable bytes and stable operation dictionaries.
No parser nodes, library objects, or raw-line classes cross this interface.
Implementations must support concurrent detached operations.
A replacement must preserve untouched structures and provide exact byte chunks
for storage; it need not use the current editor's internal representation.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EditResult:
    data: bytes
    affected_records: tuple[str, ...]
    review: dict | None = None


class GedcomEditor(Protocol):
    def validate(self, data: bytes) -> None:
        """Raise ValueError for unsupported or structurally invalid documents."""
        ...

    def apply(self, data: bytes, operations: list[dict]) -> EditResult:
        """Apply a batch to detached bytes; input is never modified."""
        ...

    def records(self, data: bytes) -> list[bytes]:
        """Return exact ordered storage chunks whose concatenation equals input."""
        ...

    def diff(self, before: bytes, after: bytes, affected: list[str] | None) -> list[str]:
        """Return a human-readable diff; affected=None compares the entire tree."""
        ...


def default_editor() -> GedcomEditor:
    """The only production selection point for the editing implementation."""
    from .document import LosslessEditor

    return LosslessEditor()
