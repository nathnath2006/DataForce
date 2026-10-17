from __future__ import annotations

import pytest
import respx
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Workspace
from app.domain.schemas import AccountIn, ContactIn
from app.services import accounts, contacts, workspaces
from tests.connectors.stubs import TamTamStub

TEST_SECRET_KEY = "ZGF0YWZvcmNlLXRlc3Qta2V5LW5vdC1mb3ItcHJvZCE="
OTHER_KEY = "b3RoZXItdGVzdC1rZXktbm90LWZvci1wcm9kLTEyMzQ="


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test", dataforce_secret_key=TEST_SECRET_KEY)


@pytest.fixture
def stub():
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as mock:
        yield TamTamStub(mock)


@pytest.fixture
def ws(db_session: Session) -> Workspace:
    row = workspaces.create_workspace(db_session, "acme-real", "Acme (real)")
    db_session.commit()
    return row


@pytest.fixture
def demo_ws(db_session: Session) -> Workspace:
    row = workspaces.create_workspace(db_session, "demo-one", "Demo", is_demo=True)
    db_session.commit()
    return row


def make_contact(db: Session, ws: Workspace, name: str = "Jane Doe"):
    account = accounts.create_account(db, ws.id, AccountIn(name="Acme Corp", domain="acme.example"))
    contact = contacts.create_contact(db, ws.id, ContactIn(account_id=account.id, full_name=name))
    db.commit()
    return contact


@pytest.fixture
def contact(db_session: Session, ws: Workspace):
    return make_contact(db_session, ws)


def seed_credential(db: Session, ws: Workspace, settings: Settings, **overrides) -> None:
    """A connected credential written directly (tokens sealed), without running the flow."""
    from datetime import UTC, datetime, timedelta

    from app.connectors import store
    from app.connectors.crypto import seal
    from tests.connectors.stubs import ACCESS_1, CLIENT_ID, ISSUER, MCP_URL, REFRESH_1

    fields = {
        "status": "connected",
        "issuer": ISSUER,
        "resource": MCP_URL,
        "client_id": CLIENT_ID,
        "client_secret_enc": None,
        "redirect_uri": "http://127.0.0.1:8800/api/connectors/tamtam/callback",
        "access_token_enc": seal(ACCESS_1, settings),
        "refresh_token_enc": seal(REFRESH_1, settings),
        "token_expires_at": datetime.now(UTC) + timedelta(hours=1),
        **overrides,
    }
    store.save_credential(db, ws.id, **fields)
    db.commit()
