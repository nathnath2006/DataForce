"""Clean, short errors for the agent tools (no stack trace, no SQL)."""

from __future__ import annotations


class ToolError(Exception):
    """A tool call that cannot be answered (unknown id, invalid filter...). The message is safe to
    show to the model: it never contains SQL, a path or a secret."""
