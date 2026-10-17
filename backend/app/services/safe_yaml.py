"""Bounded `yaml.safe_load` (SR3-11).

`safe_load` already refuses Python object tags and does not expand alias bombs, but it accepts
any size and a deeply nested document (about 10 KB) raises `RecursionError`, which used to reach
the user as a traceback. Every YAML entry point should go through `load_yaml_limited` and let the
CLI print the resulting one-line `ValueError`.
"""

from __future__ import annotations

from typing import Any

import yaml

DEFAULT_MAX_BYTES = 200_000


def load_yaml_limited(text: str, *, label: str, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
    """Parse `text` with `yaml.safe_load`. Raises ValueError (never RecursionError / YAMLError)
    for an oversized, malformed or too deeply nested document. `label` names the input in the
    message ("ICP file")."""
    # len() is a cheap lower bound on the encoded size: check it first so a huge string is not
    # copied just to be refused.
    if len(text) > max_bytes or len(text.encode("utf-8", errors="replace")) > max_bytes:
        raise ValueError(f"{label} is too large (limit {max_bytes // 1000} KB)")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {label}: {exc}") from exc
    except RecursionError:
        raise ValueError(f"{label} is nested too deeply") from None
