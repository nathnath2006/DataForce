"""Enrichment errors. Messages never contain contact values (emails, phone numbers) or tokens."""

from __future__ import annotations


class EnrichmentError(Exception):
    """An enrichment lookup failed or could not be planned."""


class EnrichmentConfigError(EnrichmentError):
    """The provider cannot be built from the current settings (e.g. missing bearer token)."""


class PaidLookupRefused(EnrichmentError):
    """A lookup that spends credits was requested without `allow_paid=True`. Nothing was sent."""
