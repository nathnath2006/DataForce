"""Client of the public French company registry (no key).

Safety rules (docs/M2A-CONTRACT.md section 5): https only, 10 s timeout, no redirect, 1 MB response
cap, query of at most 100 characters, at most 5 requests per second. Only the fields listed in
`parse_record` are read: the managers (`dirigeants`) and the `finances` are NEVER touched. A
record whose diffusion status is not "O" (open) has its address dropped.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.enrichment.errors import EnrichmentError

REQUEST_TIMEOUT_S = 10.0
MAX_RESPONSE_BYTES = 1_000_000
MAX_QUERY_CHARS = 100
MAX_REQUESTS_PER_SECOND = 5
PER_PAGE_MAX = 25

_min_interval_s = 1.0 / MAX_REQUESTS_PER_SECOND
_next_slot = 0.0


class RegistryCompany(BaseModel):
    siren: str
    name: str
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    naf_code: str | None = None
    legal_category: str | None = None
    size_bracket: str | None = None
    category: str | None = None
    created_on: date | None = None
    active: bool = False
    sole_trader: bool = False
    protected: bool = False  # non-diffusible: cannot be added to the CRM


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(REQUEST_TIMEOUT_S),
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )


async def _throttle() -> None:
    """Reserve the next request slot (no await between the read and the write, so concurrent
    callers get distinct slots) then wait for it."""
    global _next_slot
    now = time.monotonic()
    slot = max(now, _next_slot)
    _next_slot = slot + _min_interval_s
    if slot > now:
        await asyncio.sleep(slot - now)


def _str(value: object, limit: int = 300) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value[:limit]
    return None


def parse_record(raw: object) -> RegistryCompany | None:
    """The whitelisted fields of one registry record, or None when it has no valid SIREN or
    name. `dirigeants` and `finances` are never read."""
    if not isinstance(raw, dict):
        return None
    siren = _str(raw.get("siren"), 9)
    if siren is None or not re.fullmatch(r"[0-9]{9}", siren):
        return None
    name = _str(raw.get("nom_raison_sociale")) or _str(raw.get("nom_complet"))
    if name is None:
        return None
    siege = raw.get("siege")
    siege = siege if isinstance(siege, dict) else {}
    protected = raw.get("statut_diffusion") != "O" or (
        siege.get("statut_diffusion_etablissement") != "O"
    )
    complements = raw.get("complements")
    complements = complements if isinstance(complements, dict) else {}
    created: date | None = None
    created_raw = _str(raw.get("date_creation"), 10)
    if created_raw:
        try:
            created = date.fromisoformat(created_raw)
        except ValueError:
            created = None
    return RegistryCompany(
        siren=siren,
        name=name,
        address_line=None if protected else _str(siege.get("adresse")),
        postal_code=None if protected else _str(siege.get("code_postal"), 16),
        city=None if protected else _str(siege.get("libelle_commune"), 100),
        naf_code=_str(raw.get("activite_principale"), 10),
        legal_category=_str(raw.get("nature_juridique"), 10),
        size_bracket=_str(raw.get("tranche_effectif_salarie"), 8),
        category=_str(raw.get("categorie_entreprise"), 8),
        created_on=created,
        active=raw.get("etat_administratif") == "A",
        sole_trader=complements.get("est_entrepreneur_individuel") is True,
        protected=protected,
    )


def parse_results(payload: object) -> list[RegistryCompany]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise EnrichmentError("the company registry's answer has an unexpected shape")
    return [c for c in (parse_record(r) for r in results[:PER_PAGE_MAX]) if c is not None]


async def search(
    settings: Settings,
    q: str,
    *,
    page: int = 1,
    per_page: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[RegistryCompany]:
    """Search the registry. Called only on an explicit user search, never per keystroke."""
    q = q.strip()
    if not q:
        return []
    if len(q) > MAX_QUERY_CHARS:
        raise EnrichmentError(f"the registry query is longer than {MAX_QUERY_CHARS} characters")
    base = settings.registry_url.rstrip("/")
    if urlsplit(base).scheme != "https":
        raise EnrichmentError("the company registry URL must use https")
    params = {"q": q, "page": max(1, page), "per_page": max(1, min(per_page, PER_PAGE_MAX))}
    own = client is None
    http = client or new_client()
    try:
        await _throttle()
        buffer = bytearray()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_S):
                async with http.stream("GET", f"{base}/search", params=params) as response:
                    if 300 <= response.status_code < 400:
                        raise EnrichmentError("the company registry answered with a redirect")
                    if response.status_code == 429:
                        raise EnrichmentError("the company registry is rate limiting, retry later")
                    if response.status_code != 200:
                        raise EnrichmentError(
                            f"the company registry answered HTTP {response.status_code}"
                        )
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) > MAX_RESPONSE_BYTES:
                            raise EnrichmentError("the company registry's answer is too large")
        except EnrichmentError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise EnrichmentError("the company registry could not be reached") from None
        try:
            payload = json.loads(bytes(buffer))
        except (ValueError, RecursionError):
            raise EnrichmentError("the company registry's answer is not valid JSON") from None
        return parse_results(payload)
    finally:
        if own:
            await http.aclose()


async def fetch_by_siren(
    settings: Settings, siren: str, *, client: httpx.AsyncClient | None = None
) -> RegistryCompany | None:
    if not re.fullmatch(r"[0-9]{9}", siren):
        raise EnrichmentError("a SIREN has 9 digits")
    found = await search(settings, siren, per_page=5, client=client)
    return next((c for c in found if c.siren == siren), None)
