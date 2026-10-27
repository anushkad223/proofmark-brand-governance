import os, json, hashlib, hmac, sqlite3, datetime as dt, jwt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .engine import parse_docx, check, apply_fixes, DEFAULT_LIB

SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
DB = os.getenv("PROOFMARK_DB", "proofmark.db")
USERS = {"admin": "Admin", "creator": "Creator", "reviewer": "Reviewer"}
PW = os.getenv("DEMO_PASSWORD", "proofmark")
db = sqlite3.connect(DB, check_same_thread=False); db.row_factory = sqlite3.Row
db.executescript("""create table if not exists docs(id integer primary key, title text, status text, data text);
create table if not exists lib(id integer primary key check(id=1), data text);
create table if not exists log(id integer primary key, t text, who text, role text, a text, d text, hash text);""")
if not db.execute("select 1 from lib").fetchone():
    db.execute("insert into lib values(1,?)", (json.dumps(DEFAULT_LIB),)); db.commit()

app = FastAPI(title="Proofmark API", description="Check a draft against approved sources. A person decides. Never publishes.")
oauth = OAuth2PasswordBearer(tokenUrl="/api/login")
now = lambda: dt.datetime.now(dt.timezone.utc).isoformat()
def sha(s): return hashlib.sha256(s.encode()).hexdigest()
def audit(u, a, d):
    r = db.execute("select hash from log order by id desc limit 1").fetchone(); prev = r["hash"] if r else "0"; t = now()
    db.execute("insert into log(t,who,role,a,d,hash) values(?,?,?,?,?,?)", (t, u["user"], u["role"], a, d, sha(f"{prev}|{t}|{u['role']}|{a}|{d}"))); db.commit()
def user(tok=Depends(oauth)):
    try: p = jwt.decode(tok, SECRET, algorithms=["HS256"]); return {"user": p["sub"], "role": p["role"]}
    except Exception: raise HTTPException(401, "Invalid or expired token")
def need(*roles):
    def dep(u=Depends(user)):
        if u["role"] not in roles: raise HTTPException(403, f"Requires role: {' or '.join(roles)}")
        return u
    return dep
lib = lambda: json.loads(db.execute("select data from lib").fetchone()["data"])
def load(i):
    r = db.execute("select * from docs where id=?", (i,)).fetchone()
    if not r: raise HTTPException(404, "Document not found")
    d = json.loads(r["data"]); d.update(id=r["id"], title=r["title"], status=r["status"]); return d
def put(d):
    db.execute("update docs set status=?, data=? where id=?", (d["status"], json.dumps({"v": d["v"], "c": d["c"]}), d["id"])); db.commit(); return d
def add_version(d, P, why, u):
    F = check(P, lib()); prev = d["v"][-1]["F"] if d["v"] else []
    for f in F:
        o = next((x for x in prev if x["st"] == "dismissed" and x["type"] == f["type"] and x["match"] == f["match"]), None)
        if o: f["st"], f["reason"] = "dismissed", o["reason"]
    d["v"].append({"n": len(d["v"]) + 1, "P": P, "F": F}); d["status"] = "Checked"
    audit(u, "Checked", f"Version {len(d['v'])} ({why}): {len(F)} findings")

@app.post("/api/login")
def login(f: OAuth2PasswordRequestForm = Depends()):
    if f.username not in USERS or not hmac.compare_digest(f.password, PW): raise HTTPException(401, "Wrong username or password")
    tok = jwt.encode({"sub": f.username, "role": USERS[f.username], "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)}, SECRET, algorithm="HS256")
    return {"access_token": tok, "token_type": "bearer", "role": USERS[f.username]}
@app.get("/api/health")
def health(): return {"ok": True}
@app.get("/api/library")
def get_lib(u=Depends(user)): return lib()
class Lib(BaseModel): claims: list; offer: dict; terms: list
@app.put("/api/library")
def put_lib(b: Lib, u=Depends(need("Admin"))):
    db.execute("update lib set data=?", (json.dumps(b.model_dump()),)); db.commit(); audit(u, "Library", "Library updated"); return b
@app.post("/api/docs")
def upload(file: UploadFile = File(...), u=Depends(need("Creator"))):
    try: P = parse_docx(file.file)
    except Exception: raise HTTPException(400, "Could not read this file. Upload a .docx saved from Word or Google Docs.")
    if not P: raise HTTPException(400, "The document has no text.")
    cur = db.execute("insert into docs(title,status,data) values(?,?,?)", (file.filename, "Draft", "{}")); d = {"id": cur.lastrowid, "title": file.filename, "status": "Draft", "v": [], "c": []}
    audit(u, "Uploaded", file.filename); add_version(d, P, "first check", u); return put(d)
@app.get("/api/docs")
def docs(u=Depends(user)): return [{"id": r["id"], "title": r["title"], "status": r["status"]} for r in db.execute("select * from docs order by id desc")]
@app.get("/api/docs/{i}")
def get_doc(i: int, u=Depends(user)): return load(i)
class Decision(BaseModel): action: str; text: str = ""; reason: str = ""
@app.post("/api/docs/{i}/findings/{fid}")
def decide(i: int, fid: str, b: Decision, u=Depends(need("Creator"))):
    d = load(i)
    if d["status"] != "Checked": raise HTTPException(409, "Findings can be decided only while the document is Checked")
    f = next((x for x in d["v"][-1]["F"] if x["id"] == fid), None)
    if not f: raise HTTPException(404, "Finding not found")
    if b.action == "accept": f["st"] = "accepted"
    elif b.action == "edit":
        if not b.text.strip(): raise HTTPException(422, "Edit needs replacement text")
        f["st"], f["newText"] = "edited", b.text.strip()
    elif b.action == "dismiss":
        if not b.reason.strip(): raise HTTPException(422, "Dismissing needs a reason")
        f["st"], f["reason"] = "dismissed", b.reason.strip()
    elif b.action == "undo": f["st"] = "open"; f.pop("reason", None)
    else: raise HTTPException(422, "action must be accept, edit, dismiss or undo")
    audit(u, b.action.capitalize(), f"{fid} {f['type']}" + (f": {b.reason}" if b.reason else "")); return put(d)
@app.post("/api/docs/{i}/submit")
def submit(i: int, u=Depends(need("Creator"))):
    d = load(i)
    if d["status"] != "Checked": raise HTTPException(409, "Only a Checked document can be submitted")
    if any(f["st"] == "open" for f in d["v"][-1]["F"]): raise HTTPException(409, "Decide on every finding first")
    d["status"] = "In review"; audit(u, "Submitted for review", f"Version {d['v'][-1]['n']}"); return put(d)
class Review(BaseModel): decision: str; note: str = ""
@app.post("/api/docs/{i}/review")
def review(i: int, b: Review, u=Depends(need("Reviewer"))):
    d = load(i)
    if d["status"] != "In review": raise HTTPException(409, "Document is not in review")
    if b.note.strip(): d["c"].append({"role": u["role"], "t": now(), "x": b.note.strip()})
    if b.decision == "approve": d["status"] = "Approved"; audit(u, "Approved", f"Version {d['v'][-1]['n']}")
    elif b.decision == "back":
        if not b.note.strip(): raise HTTPException(422, "Sending back needs a note")
        d["status"] = "Changes requested"; audit(u, "Sent back", b.note)
    else: raise HTTPException(422, "decision must be approve or back")
    return put(d)
@app.post("/api/docs/{i}/versions")
def new_version(i: int, u=Depends(need("Creator"))):
    d = load(i)
    if d["status"] != "Changes requested": raise HTTPException(409, "A new version needs Changes requested")
    v = d["v"][-1]; add_version(d, apply_fixes(v["P"], v["F"]), "accepted fixes applied", u); return put(d)
class Comment(BaseModel): text: str
@app.post("/api/docs/{i}/comments")
def comment(i: int, b: Comment, u=Depends(need("Creator", "Reviewer"))):
    d = load(i); d["c"].append({"role": u["role"], "t": now(), "x": b.text}); audit(u, "Commented", b.text); return put(d)
@app.get("/api/audit")
def get_audit(u=Depends(user)): return [dict(r) for r in db.execute("select * from log order by id")]
@app.get("/api/audit/verify")
def verify(u=Depends(user)):
    prev = "0"
    for r in db.execute("select * from log order by id"):
        if r["hash"] != sha(f"{prev}|{r['t']}|{r['role']}|{r['a']}|{r['d']}"): return {"intact": False, "broken_at": r["id"]}
        prev = r["hash"]
    return {"intact": True, "entries": db.execute("select count(*) c from log").fetchone()["c"]}
app.mount("/samples", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "samples")), name="samples")
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "web"), html=True), name="web")
