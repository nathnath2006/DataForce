"""Append-only notes and comments through the API: no edit, corrections are new rows."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def setup(client: TestClient):
    client.post("/api/workspaces", json={"slug": "n1", "name": "N1"})
    client.post("/api/workspaces", json={"slug": "n2", "name": "N2"})
    ws = "/api/w/n1"
    acc = client.post(f"{ws}/accounts", json={"name": "Acme"}).json()
    contact = client.post(
        f"{ws}/contacts", json={"account_id": acc["id"], "full_name": "Jo"}
    ).json()
    user = client.post(f"{ws}/users", json={"display_name": "Ann"}).json()
    return ws, acc["id"], contact["id"], user["id"]


@pytest.mark.parametrize("kind", ["note", "comment"])
def test_append_only_lifecycle(client, setup, kind):
    ws, account_id, contact_id, user_id = setup
    parent = f"contacts/{contact_id}/notes" if kind == "note" else f"accounts/{account_id}/comments"
    item = f"{kind}s"
    created = client.post(f"{ws}/{parent}", json={"body": "first", "author_id": user_id})
    assert created.status_code == 201
    first = created.json()
    assert first["author_name"] == "Ann" and first["corrects_id"] is None
    # correct: a NEW row, the original stays
    fixed = client.post(
        f"{ws}/{item}/{first['id']}/correct", json={"body": "second", "author_id": user_id}
    )
    assert fixed.status_code == 201
    second = fixed.json()
    assert second["id"] != first["id"] and second["corrects_id"] == first["id"]
    history = client.get(f"{ws}/{item}/{second['id']}/history").json()
    assert [h["body"] for h in history] == ["first", "second"]  # oldest first
    assert [h["body"] for h in client.get(f"{ws}/{item}/{first['id']}/history").json()] == [
        "first",
        "second",
    ]
    listed = client.get(f"{ws}/{parent}").json()
    assert [n["body"] for n in listed] == ["second"]  # current versions only
    # no way to edit in place
    assert client.patch(f"{ws}/{item}/{first['id']}", json={"body": "x"}).status_code == 405
    assert client.put(f"{ws}/{item}/{first['id']}", json={"body": "x"}).status_code == 405
    # soft delete returns the row, history survives
    deleted = client.delete(f"{ws}/{item}/{second['id']}", params={"by_id": user_id})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None and deleted.json()["deleted_by_name"] == "Ann"
    assert client.get(f"{ws}/{parent}").json() == []
    hist = client.get(f"{ws}/{item}/{second['id']}/history").json()
    assert len(hist) == 2 and all(h["deleted_at"] for h in hist)
    assert client.delete(f"{ws}/{item}/{second['id']}").status_code == 422  # already deleted
    assert client.post(f"{ws}/{item}/{second['id']}/correct", json={"body": "z"}).status_code == 422


@pytest.mark.parametrize("kind", ["note", "comment"])
def test_validation_and_foreign_ids(client, setup, kind):
    ws, account_id, contact_id, user_id = setup
    parent = f"contacts/{contact_id}/notes" if kind == "note" else f"accounts/{account_id}/comments"
    item = f"{kind}s"
    assert client.post(f"{ws}/{parent}", json={"body": ""}).status_code == 422
    assert client.post(f"{ws}/{parent}", json={"body": "x" * 20_001}).status_code == 422
    assert (
        client.post(
            f"{ws}/{parent}", json={"body": "x", "author_id": str(uuid.uuid4())}
        ).status_code
        == 404
    )
    made = client.post(f"{ws}/{parent}", json={"body": "mine"}).json()
    assert made["author_name"] is None
    other = "/api/w/n2"
    assert client.get(f"{other}/{item}/{made['id']}/history").status_code == 404
    assert (
        client.post(f"{other}/{item}/{made['id']}/correct", json={"body": "x"}).status_code == 404
    )
    assert client.delete(f"{other}/{item}/{made['id']}").status_code == 404
    assert client.get(f"{other}/{parent}").status_code == 404
    assert client.post(f"{other}/{parent}", json={"body": "x"}).status_code == 404
    assert client.get(f"{ws}/{parent}").json()[0]["body"] == "mine"


def test_note_count_on_contact_and_newest_first(client, setup):
    ws, _, contact_id, _ = setup
    for body in ("a", "b", "c"):
        client.post(f"{ws}/contacts/{contact_id}/notes", json={"body": body})
    assert [n["body"] for n in client.get(f"{ws}/contacts/{contact_id}/notes").json()] == [
        "c",
        "b",
        "a",
    ]
    assert client.get(f"{ws}/contacts/{contact_id}").json()["n_notes"] == 3
