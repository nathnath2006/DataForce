"""Title endpoints and service (fake provider, never the network)."""

from __future__ import annotations

import pytest

from app.api.routes.titles import get_title_factory
from app.llm.fake import FakeLLM
from app.titles.ai import TitleAnswer

pytestmark = pytest.mark.integration
KEY = "AIzaSyTESTKEY-0123456789abcdefghij"


@pytest.fixture
def fake(app):
    box = {"llm": None, "n": 0}

    def factory(provider, *, api_key, model, settings, usage):
        llm = FakeLLM(usage=usage)
        llm.register(
            TitleAnswer,
            lambda s, u: TitleAnswer(function="hr", seniority="manager", confidence="medium"),
        )
        box["llm"] = llm
        return llm

    app.dependency_overrides[get_title_factory] = lambda: factory
    return box


@pytest.fixture
def ws(client):
    assert client.post("/api/workspaces", json={"slug": "t1", "name": "T1"}).status_code == 201
    return "/api/w/t1"


@pytest.fixture
def acc(client, ws):
    r = client.post(f"{ws}/accounts", json={"name": "Acme"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add(client, ws, acc, name, title):
    r = client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": name, "title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def configure(client, ws):
    r = client.put(f"{ws}/ai", json={"provider": "gemini", "model": "m", "api_key": KEY})
    assert r.status_code == 200, r.text


def run(client, ws, **body):
    r = client.post(f"{ws}/titles/normalize", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def review(client, ws):
    return {i["full_name"]: i for i in client.get(f"{ws}/titles/review").json()}


def test_create_classifies(client, ws, acc):
    add(client, ws, acc, "Ann Alpha", "DAF")
    it = review(client, ws)["Ann Alpha"]
    assert (it["function"], it["seniority"], it["source"]) == ("finance", "c_level", "dictionary")
    cid = add(client, ws, acc, "Bob Beta", None)
    assert review(client, ws)["Bob Beta"]["flag"] == "no title"
    r = client.patch(f"{ws}/contacts/{cid}", json={"title": "Sales Manager"})
    assert r.status_code == 200, r.text
    assert review(client, ws)["Bob Beta"]["function"] == "sales"


def test_preview(client, ws):
    r = client.get(f"{ws}/titles/preview", params={"title": "Dir. marketing"}).json()
    assert r["normalized"] == "directeur marketing" and r["source"] == "dictionary"
    assert client.get(f"{ws}/titles/preview", params={"title": "zzz"}).json()["source"] == "none"


def test_no_ai_configured(client, ws, acc, fake):
    add(client, ws, acc, "Cy Gamma", "Zorglub")
    out = run(client, ws)
    assert out["ai_configured"] is False and out["llm_calls"] == 0
    assert review(client, ws)["Cy Gamma"]["flag"] == "unknown title (no AI model configured)"
    assert out["by_source"]["unknown"] == 1


def test_ai_cache_cap_and_privacy(client, ws, acc, fake, api_settings):
    configure(client, ws)
    add(client, ws, acc, "Secret Person", "Zorglub")
    add(client, ws, acc, "Other Human", "Zorglub")
    out = run(client, ws)
    assert out["llm_calls"] == 1 and out["by_source"]["llm"] == 2
    it = review(client, ws)["Secret Person"]
    assert it["source"] == "llm" and it["flag"] == "classified by AI (confidence medium): check"
    out2 = run(client, ws)
    assert out2["llm_calls"] == 0 and out2["by_source"]["llm"] == 2
    # prompts: titles only
    assert fake["llm"] is not None
    # cap
    api_settings.titles_max_llm_calls_per_run = 1
    add(client, ws, acc, "Third One", "Quux")
    add(client, ws, acc, "Fourth One", "Frobnicate")
    out3 = run(client, ws)
    assert out3["llm_calls"] == 1
    flags = [i["flag"] for i in review(client, ws).values()]
    assert "unknown title (AI call limit reached)" in flags


def test_prompts_never_contain_names(client, ws, acc, app):
    prompts = []

    def factory(provider, *, api_key, model, settings, usage):
        llm = FakeLLM(usage=usage)

        def h(s, u):
            prompts.append(s + u)
            return TitleAnswer(function="tech", seniority="head", confidence="high")

        llm.register(TitleAnswer, h)
        return llm

    app.dependency_overrides[get_title_factory] = lambda: factory
    configure(client, ws)
    add(client, ws, acc, "Zebulon Quibble", "Zorglub")
    run(client, ws)
    assert prompts and all("Zebulon" not in p and "Quibble" not in p for p in prompts)
    assert any("zorglub" in p for p in prompts)


def test_manual_never_overwritten(client, ws, acc, fake):
    configure(client, ws)
    cid = add(client, ws, acc, "Dee Delta", "CEO")
    r = client.put(f"{ws}/contacts/{cid}/title-class", json={"function": "hr", "seniority": "vp"})
    assert r.status_code == 200 and r.json()["source"] == "manual" and r.json()["flag"] is None
    out = run(client, ws)
    assert out["by_source"]["manual"] == 1
    it = review(client, ws)["Dee Delta"]
    assert (it["function"], it["seniority"]) == ("hr", "vp")
    client.patch(f"{ws}/contacts/{cid}", json={"title": "Sales Manager"})
    assert review(client, ws)["Dee Delta"]["function"] == "hr"
    bad = client.put(
        f"{ws}/contacts/{cid}/title-class", json={"function": "nope", "seniority": "vp"}
    )
    assert bad.status_code == 422
