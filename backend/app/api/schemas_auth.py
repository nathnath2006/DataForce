"""Request and response bodies for sign-in and user management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AuthStatus(BaseModel):
    setup_needed: bool
    signed_in: bool


class SetupIn(_In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)


class LoginIn(_In):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(max_length=200)


class AuthUserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_admin: bool


class MembershipOut(BaseModel):
    workspace_slug: str
    workspace_name: str
    role: Literal["admin", "rep"]
    see_all: bool
    delete_own: bool
    app_user_id: UUID | None
    app_user_name: str | None


class MeOut(BaseModel):
    user: AuthUserOut
    memberships: list[MembershipOut]


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    is_admin: bool
    disabled: bool
    has_password: bool
    role: Literal["admin", "rep"]
    see_all: bool
    delete_own: bool
    app_user_id: UUID | None
    app_user_name: str | None
    last_login_at: datetime | None


class MemberCreate(_In):
    """Create a person (display_name + password) or add an existing account (email only)."""

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "rep"] = "rep"
    see_all: bool = False
    delete_own: bool = False
    app_user_id: UUID | None = None


class MemberUpdate(_In):
    role: Literal["admin", "rep"] | None = None
    see_all: bool | None = None
    delete_own: bool | None = None
    app_user_id: UUID | None = None
    clear_app_user: bool = False  # explicit, because null alone means "unchanged"
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class PasswordReset(_In):
    password: str = Field(max_length=200)
