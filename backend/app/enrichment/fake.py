"""Offline `EnrichmentProvider` for tests and demos.

Behaves like the real client where it matters: same assumed credit costs, same paid guard (so
callers' `allow_paid` handling is exercised, strictly: `allow_paid is True`), deterministic
output. Values are synthetic: emails always use the reserved `.example` TLD and
mobiles sit in ARCEP's fiction range (06 39 98 xx xx), so they can never reach a real person.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata

from app.domain.schemas import EnrichmentRequest, EnrichmentResult
from app.enrichment.errors import EnrichmentConfigError, PaidLookupRefused
from app.enrichment.tamtam_mcp import DEFAULT_CREDIT_COSTS


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower()) or "x"


class FakeEnrichmentProvider:
    name = "fake"

    def __init__(self, credit_costs: dict[str, float] | None = None) -> None:
        self._costs = {**DEFAULT_CREDIT_COSTS, **(credit_costs or {})}
        for name, cost in self._costs.items():
            if isinstance(cost, bool) or not math.isfinite(cost) or cost < 0:
                raise EnrichmentConfigError(f"credit_costs[{name!r}] must be a finite number >= 0")
        self.calls = 0  # lookups actually served (refused ones are not counted)

    async def enrich_contact(
        self, request: EnrichmentRequest, *, allow_paid: bool
    ) -> EnrichmentResult:
        wants = list(dict.fromkeys(request.want))
        cost = sum(self._costs.get(w, 0.0) for w in wants)
        if cost > 0 and allow_paid is not True:
            raise PaidLookupRefused(
                f"{'+'.join(wants)} lookup would cost {cost:g} credit(s) and allow_paid is False"
            )
        self.calls += 1
        parts = request.full_name.split()
        first, last = _slug(parts[0]), _slug(parts[-1])
        # Always the reserved `.example` TLD, even when the request carries a real domain: a fake
        # lookup must never produce an address on a real person's mail server (SR2-07).
        domain = f"{_slug(request.company_domain or request.company_name)}.example"
        digest = hashlib.blake2b(
            f"{request.full_name}|{request.company_name}".encode(), digest_size=4
        ).digest()
        mobile_tail = int.from_bytes(digest, "big") % 100
        return EnrichmentResult(
            provider=self.name,
            email=f"{first}.{last}@{domain}" if "email" in wants else None,
            mobile=f"+33 6 39 98 {mobile_tail // 10}{mobile_tail % 10} 00"
            if "mobile" in wants
            else None,
            credits_used=cost,
            source="fake",
            raw_tool="fake_enrich_contact",
        )
