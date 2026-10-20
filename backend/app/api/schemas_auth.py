"""Request and response bodies for sign-in and user management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DemoLogin(BaseModel):
    email: str
    display_name: str


class AuthStatus(BaseModel):
    setup_needed: bool
    signed_in: bool
    demo_logins: list[DemoLogin] = []
    signup_enabled: bool = True
    demo_available: bool = False  # the "Try the demo" button works


class ForgotIn(_In):
    email: str = Field(min_length=1, max_length=320)


class ResetIn(_In):
    token: str = Field(min_length=1, max_length=500)
    password: str = Field(max_length=200)


class SetupIn(_In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)


class SignupIn(_In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=200)
    mode: Literal["create", "join"]
    code: str = Field(min_length=1, max_length=200)  # a creation code, or a join token


class JoinIn(_In):
    token: str = Field(min_length=1, max_length=200)


class LoginIn(_In):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(max_length=200)


class AuthUserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_admin: bool
    workspace_credits: int = 0  # workspaces this person may still create
    is_demo: bool = False  # a public-demo account


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


class DemoStartIn(_In):
    """Who to be in the demo: "admin" (default) or the app_user id of a rep."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    as_: str | None = Field(default=None, alias="as", max_length=36)


class DemoIdentity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    as_: str = Field(alias="as")
    label: str
    role: Literal["admin", "rep"]


class DemoAiKeyIn(_In):
    provider: Literal["gemini", "anthropic"]
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    api_key: str = Field(min_length=1, max_length=400)


class DemoAiKeyOut(BaseModel):
    """The visitor's session AI key. The key itself is never returned."""

    provider: Literal["gemini", "anthropic"] | None = None
    model: str | None = None
    set: bool = False
