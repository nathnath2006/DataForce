"""Sign-in helpers for tests (see the `client`, `anon_client` and `make_member` fixtures)."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import passwords, sessions
from app.db.models import Membership, UserAccount, Workspace

MEMBER_PASSWORD = "member-password-1"
_counter = itertools.count(1)


@dataclass(frozen=True)
class Member:
    email: str
    password: str
    user_id: uuid.UUID


def sign_in_superadmin(client: TestClient, factory: sessionmaker[Session]) -> UserAccount:
    with factory() as s:
        user = UserAccount(
            email=f"root{next(_counter)}@test.local",
            display_name="Test Admin",
            password_hash=None,
            is_admin=True,
        )
        s.add(user)
        s.flush()
        token = sessions.create_session(s, user, "pytest")
        s.commit()
    client.cookies.set(sessions.COOKIE, token)
    return user


def make_member_in(
    factory: sessionmaker[Session],
    ws_slug: str,
    role: str = "rep",
    see_all: bool = False,
    delete_own: bool = False,
    app_user_id: uuid.UUID | None = None,
) -> Member:
    with factory() as s:
        ws = s.scalars(select(Workspace).where(Workspace.slug == ws_slug)).one()
        n = next(_counter)
        email = f"member{n}@test.local"
        user = UserAccount(
            email=email,
            display_name=f"Member {n}",
            password_hash=None if ws.is_demo else passwords.hash_password(MEMBER_PASSWORD),
        )
        s.add(user)
        s.flush()
        s.add(
            Membership(
                user_account_id=user.id,
                workspace_id=ws.id,
                role=role,
                see_all=see_all,
                delete_own=delete_own,
                app_user_id=app_user_id,
            )
        )
        s.commit()
        return Member(email, "" if ws.is_demo else MEMBER_PASSWORD, user.id)


def login_as(client: TestClient, email: str, password: str = "") -> None:
    """Replace the client's session by a login as `email` (asserts it worked)."""
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
