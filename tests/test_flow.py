import os, tempfile
os.environ["PROOFMARK_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
def H(u):
    t = c.post("/api/login", data={"username": u, "password": "proofmark"}).json()["access_token"]; return {"Authorization": "Bearer " + t}
SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "spring_offer_email.docx")
def test_full_workflow():
    cr, rv = H("creator"), H("reviewer")
    d = c.post("/api/docs", files={"file": open(SAMPLE, "rb")}, headers=cr).json()
    assert d["status"] == "Checked" and len(d["v"][0]["F"]) == 8
    assert all(f["rule"] and f["msg"] for f in d["v"][0]["F"])
    i = d["id"]
    assert c.post(f"/api/docs/{i}/submit", headers=cr).status_code == 409      # open findings block submit
    assert c.post(f"/api/docs/{i}/findings/F1", json={"action": "dismiss"}, headers=cr).status_code == 422  # reason required
    assert c.post(f"/api/docs/{i}/findings/F1", json={"action": "accept"}, headers=rv).status_code == 403  # role enforced
    for f in d["v"][0]["F"]:
        a = {"action": "dismiss", "reason": "Brand voice, approved by legal"} if f["type"] == "Terminology" else {"action": "accept"}
        assert c.post(f"/api/docs/{i}/findings/{f['id']}", json=a, headers=cr).status_code == 200
    assert c.post(f"/api/docs/{i}/submit", headers=cr).json()["status"] == "In review"
    assert c.post(f"/api/docs/{i}/review", json={"decision": "back", "note": "Re-check the offer date"}, headers=rv).json()["status"] == "Changes requested"
    d2 = c.post(f"/api/docs/{i}/versions", headers=cr).json()
    assert len(d2["v"]) == 2 and d2["v"][1]["n"] == 2
    fixed = " ".join(p["text"] for p in d2["v"][1]["P"])
    assert "#1" not in fixed and "15 Dec" in fixed and "20% off" in fixed
    left = d2["v"][1]["F"]; assert all(f["type"] == "Terminology" and f["st"] == "dismissed" for f in left)  # dismissals carried over
    assert c.post(f"/api/docs/{i}/submit", headers=cr).json()["status"] == "In review"
    assert c.post(f"/api/docs/{i}/review", json={"decision": "approve"}, headers=rv).json()["status"] == "Approved"
    assert c.get("/api/audit/verify", headers=cr).json()["intact"] is True
def test_auth_and_library():
    assert c.get("/api/library").status_code == 401
    assert c.post("/api/login", data={"username": "creator", "password": "x"}).status_code == 401
    lib = c.get("/api/library", headers=H("admin")).json(); lib["offer"]["disc"] = 30
    assert c.put("/api/library", json=lib, headers=H("creator")).status_code == 403
    assert c.put("/api/library", json=lib, headers=H("admin")).status_code == 200
