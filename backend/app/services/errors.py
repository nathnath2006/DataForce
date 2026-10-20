"""Errors raised by the services layer."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class, so callers can catch every services failure at once."""


class NotFoundError(ServiceError, LookupError):
    """The referenced row does not exist."""


class AlreadyExistsError(ServiceError, ValueError):
    """A row with the same unique key already exists."""


class InvalidInputError(ServiceError, ValueError):
    """A value was refused at the service boundary (for example a non-http(s) URL). Subclasses
    ValueError so callers that already catch ValueError for bad rows keep working."""


class ForbiddenError(ServiceError, PermissionError):
    """The member may not do this (an admin-only action, or a delete without the right)."""
