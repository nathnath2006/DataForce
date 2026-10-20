import re, uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import select
from app.db.models import Workspace
from tests.api.auth_helpers import login_as

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)

def build(client):
    base = "/api/w/vis"
    client.post("/api/workspaces", json={"slug": "vis", "name": "Vis"})
    client.post("/api/workspaces", json={"slug": "other", "name": "Other"})
    a = client.post(f"{base}/users", json={"display_name": "Rep A"}).json()["id"]
    b = client.post(f"{base}/users", json={"display_name": "Rep B"}).json()["id"]
    ids = {}
    day = (NOW - timedelta(days=30)).date().isoformat()
    for key, owner in (("accA", a), ("accB", b), ("accS", None)):
        body = {"name": key, **({"owner_id": owner} if owner else {})}
        ids[key] = client.post(f"{base}/accounts", json=body).json()["id"]
    ids["dB"] = client.post(f"{base}/deals", json={"account_id": ids["accB"], "name": "dB", "created_on": day, "amount_eur": "5000", "owner_id": b}).json()["id"]
    ids["dA"] = client.post(f"{base}/deals", json={"account_id": ids["accA"], "name": "dA", "created_on": day, "amount_eur": "10", "owner_id": a}).json()["id"]
    ids["dSA"] = client.post(f"{base}/deals", json={"account_id": ids["accS"], "name": "dSA", "created_on": day, "amount_eur": "10", "owner_id": a}).json()["id"]
    ids["dSB"] = client.post(f"{base}/deals", json={"account_id": ids["accS"], "name": "SECRETdSB", "created_on": day, "amount_eur": "7777", "owner_id": b}).json()["id"]
    for k in ("accA", "accB", "accS"):
        ids["c"+k] = client.post(f"{base}/contacts", json={"account_id": ids[k], "full_name": f"Person {k}"}).json()["id"]
        ids["n"+k] = client.post(f"{base}/contacts/{ids['c'+k]}/notes", json={"body": f"note {k}"}).json()["id"]
        ids["m"+k] = client.post(f"{base}/accounts/{ids[k]}/comments", json={"body": f"comment {k}"}).json()["id"]
    ids["act"] = client.post(f"{base}/activities", json={"deal_id":ids["dSB"],"kind":"call","occurred_at":NOW.isoformat(),"subject":"SECRETACT"})
    print("act", ids["act"].status_code, ids["act"].text[:200]); ids["act"]=ids["act"].json().get("id")
    ids["task"] = client.post(f"{base}/tasks", json={"title":"SECRETTASK","deal_id":ids["dSB"]}).json().get("id")
    ids["taskB"] = client.post(f"{base}/tasks", json={"title":"SECRETTASKB","account_id":ids["accB"]}).json().get("id")
    return ids, a, b

def test_probe(client, make_member, app, session_factory):
    ids, a, b = build(client)
    spec = app.openapi()
    ma = make_member("vis", app_user_id=uuid.UUID(a))
    mo = make_member("other")
    sub = {"ws": "vis", "account_id": ids["accB"], "deal_id": ids["dB"], "contact_id": ids["caccB"], "note_id": ids["naccB"], "comment_id": ids["maccB"], "activity_id": ids["act"], "task_id": ids["taskB"], "user_id": str(uuid.uuid4())}
    routes = []
    for p, ops in spec["paths"].items():
        for m in ops:
            if m in ("get","post","put","patch","delete"):
                routes.append((m.upper(), p))
    def fill(p, sub):
        def r(mo_):
            k = mo_.group(1)
            return str(sub.get(k, uuid.uuid4()))
        return re.sub(r"\{(\w+)\}", r, p)
    # non-member matrix
    login_as(client, mo.email, mo.password)
    for m,p in routes:
        if "/w/" not in p: continue
        url = fill(p, sub)
        r = client.request(m, url, json={} if m!="GET" else None)
        if r.status_code not in (404, 405, 422) :
            print("NONMEMBER", m, p, r.status_code, r.text[:100])
        elif r.status_code == 422: print("NONMEMBER422", m, p)
    # rep A as GET leak
    login_as(client, ma.email, ma.password)
    for m,p in routes:
        if "/w/" not in p: continue
        url = fill(p, sub)
        r = client.request(m, url, json={} if m!="GET" else None)
        leak = any(s in r.text for s in ("accB","dB","SECRET","Person accB","note accB","comment accB"))
        print("REP", m, p, r.status_code, "LEAK" if leak else "")
        if leak: print("   ", r.text[:600])


def test_probe2(client, make_member, app, session_factory):
    ids, a, b = build(client)
    base="/api/w/vis"
    # B's deal activities + stage move as admin, on shared acc
    r=client.post(f"{base}/accounts/{ids['accS']}/activities", json={"deal_id":ids["dSB"],"kind":"call","occurred_at":NOW.isoformat(),"subject":"SECRETACT"}); print("mkact",r.status_code,r.text[:150])
    r=client.post(f"{base}/deals/{ids['dSB']}/move", json={"stage":"qualification"}); print("move",r.status_code)
    ma = make_member("vis", app_user_id=uuid.UUID(a)); login_as(client, ma.email, ma.password)
    S=ids["accS"]
    for path in (f"accounts/{S}/timeline", f"accounts/{S}/activities", f"accounts/{S}/tasks", f"accounts/{S}", f"accounts/{S}/org-chart", f"accounts/{S}/comments", f"deals?account_id={S}", "deals", "contacts", "companies", "lookup?q=acc", "lookup?q=SECRET", "stats/pipeline","admin/overview","quality","workspaces",f"deals/{ids['dSB']}",f"deals/{ids['dSB']}/stage-events",f"deals/{ids['dSB']}/timeline", "users", "agent", "ai", "mailbox","mailbox/messages","themes/latest","assistant/scope?x=1","models","flows","workbooks","stats/scan/latest","titles/review","documents"):
        r=client.get(f"{base}/{path}" if path!="workspaces" else "/api/workspaces")
        leak=[k for k in ("SECRET","dB","accB","5000","7777","Person accB") if k in r.text]
        print(r.status_code, path, leak, r.text[:0])
        if leak and r.status_code==200: print("    ", r.text[:500])
    for path,body in ((f"accounts/{S}/activities",{"deal_id":ids["dSB"],"kind":"note","occurred_at":NOW.isoformat(),"subject":"AWRITE"}),
        ("tasks",{"title":"AT","deal_id":ids["dSB"]}),
        ("tasks",{"title":"AT2","deal_id":ids["dB"]}),
        (f"deals/{ids['dSB']}/move",{"stage":"won"}),
        ("tasks",{"title":"AT3","account_id":S,"owner_id":b}),
        (f"contacts/{ids['caccS']}/notes",{"body":"n","author_id":b}),
        ):
        r=client.post(f"{base}/{path}",json=body); print("WRITE",path,body.get("deal_id"),r.status_code,r.text[:200])
