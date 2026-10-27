# Proofmark: check it before it ships
Team TrueNorth (Anushka Dakare) | Inkloom AI: Brand Governance | Round 2

Checks a DOCX draft against approved sources, explains each issue with the rule it cites, and leaves the decision to a person. Never publishes.

Live project: <paste deployed link>   Repository: <paste GitHub link>

## Run it
    pip install -r requirements.txt
    uvicorn app.main:app --reload        # app at http://localhost:8000, API docs at /docs
    pytest                               # end-to-end workflow tests
    docker build -t proofmark . && docker run -p 8000:8000 proofmark

Demo logins (password `proofmark`): `admin`, `creator`, `reviewer`. The interface logs in with these automatically when the role buttons are used. Set JWT_SECRET in production. If you change DEMO_PASSWORD, update the password in `web/index.html` too.

The interface has two modes, shown by a badge in the header: connected to this server (every action uses the API), or browser demo mode when opened without a server.

## Structure
- `app/engine.py`: DOCX parsing (python-docx) and the rule engine (claims, expired claims, offer facts, glossary, contrast, alt text)
- `app/main.py`: FastAPI API, JWT roles, SQLite storage, workflow rules, SHA-256 hash-chained audit log
- `web/index.html`: interface (overview, guided demo, workspace, library, audit log, judges page); uses the API when served by this server
- `docs/Proofmark_Round2_Project_Document.docx`: the Round 2 project document (add your two links before exporting to PDF)
- `tests/test_flow.py`: upload, decide, submit, send back, new version, approve, audit verify, role enforcement
- `samples/`: spring_offer_email.docx (8 findings), social_post_issues.docx (6), brochure_missing_alt.docx (4), clean_draft.docx (0)

## Workflow API (Creator / Reviewer / Admin enforced server-side)
POST /api/login, GET/PUT /api/library, POST /api/docs (upload), POST /api/docs/{id}/findings/{fid} (accept, edit, dismiss with reason, undo), /submit, /review (approve or back with note), /versions, /comments, GET /api/audit, /api/audit/verify.

## Completed features
Source library, DOCX upload and parsing, six check types with cited rules and approved fixes, accept/edit/dismiss, status flow, reviewer approve or send back, versioning with re-check and carried-over dismissals, comments, hash-chained audit log, JWT roles.

## Changes from the Round 1 plan
SQLite instead of PostgreSQL for the demo (PostgreSQL arrives with workspaces in Round 3); no AI judge yet (rules only).

## Three Round 3 improvements
1. AI judge with source-quote verification (retrieval over the library; every quote verified).
2. Multi-user workspaces on PostgreSQL where agencies see only their own documents.
3. Insights: rules dismissed often are flagged for the owner, plus an independent test set with precision and recall.
