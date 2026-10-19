"""One rule for column names that may hold secrets or personal contact data (SR14-02, SR16-01):
their values are never shown (agent flow output, flow profiles)."""

from __future__ import annotations

import re

SENSITIVE = re.compile(
    r"(?i)^(?:.*_enc|(?:.*[_\- .])?(?:password|passwd|secret|token|api_key|apikey|email|e-mail"
    r"|mail|phone|mobile|tel|telephone|téléphone))$"
)
