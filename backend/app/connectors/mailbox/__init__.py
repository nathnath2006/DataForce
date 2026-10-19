"""Read-only mailbox providers (Gmail, Outlook). Every provider module exposes the same functions
(see `base`); `PROVIDERS` maps the provider name to its module."""

from __future__ import annotations

from app.connectors.mailbox import google, microsoft

PROVIDERS = {"gmail": google, "outlook": microsoft}
