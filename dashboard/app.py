"""Dashboard backend: reads processed data from the database and serves it as JSON + the static dashboard page.

    uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
No model calls happen here; the AI recommendations shown are the saved memo-agent output with its claim check.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select

from . import db

app = FastAPI(title="Spotify review insight API", version="1.0")
eng = db.engine()
STATIC = Path(__file__).resolve().parent / "static"


def rows(stmt):
    with eng.connect() as con:
        return [dict(r._mapping) for r in con.execute(stmt)]


def doc(key):
    r = rows(select(db.documents.c.body).where(db.documents.c.key == key))
    return r[0]["body"] if r else None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    n = rows(select(func.count()).select_from(db.records))[0]
    return {"ok": True, "records_in_db": list(n.values())[0], "database": eng.dialect.name}


@app.get("/api/summary")
def summary():
    rs = doc("record_summary") or {}
    run = doc("run_summary") or {}
    ing = doc("ingestion") or {}
    ver = doc("verification") or {}
    gold = doc("golden") or {}
    cost = doc("cost") or {}
    db_counts = rows(select(db.records.c.intent, func.count().label("n")).group_by(db.records.c.intent))
    return {"records": rs, "ingestion": {k: ing.get(k) for k in ("rows", "input_sha256", "distinct_nonempty_texts", "profile",
                                                                  "scope", "scope_detail", "first_review", "last_review")},
            "intent_counts_in_db": {r["intent"]: r["n"] for r in db_counts},
            "calls_by_role": run.get("calls_by_role"), "total_cost_usd": run.get("total_cost_usd_from_usage"),
            "sessions": run.get("sessions"), "config": run.get("config"),
            "verification": ver, "golden": {k: v for k, v in gold.items() if not isinstance(v, dict)} if gold else None,
            "planted": {k: v for k, v in (doc("planted") or {}).items() if k != "cases"} or None,
            "injection": doc("injection"), "pilot_projection": (cost.get("projections") if cost else None)}


@app.get("/api/areas")
def areas():
    return rows(select(db.areas).order_by(db.areas.c.severity_sum.desc()))


@app.get("/api/ranking")
def ranking(limit: int = Query(50, le=500)):
    return rows(select(db.issues).order_by(db.issues.c.rank).limit(limit))


@app.get("/api/issues/{issue_id}")
def issue(issue_id: str, limit: int = Query(12, le=100)):
    r = rows(select(db.issues).where(db.issues.c.issue_id == issue_id))
    if not r:
        raise HTTPException(404, "unknown issue")
    sev = rows(select(db.records.c.severity, func.count().label("n")).where(db.records.c.issue_id == issue_id)
               .group_by(db.records.c.severity).order_by(db.records.c.severity))
    examples = rows(select(db.records.c.review_id, db.records.c.evidence_quote, db.records.c.severity, db.records.c.intent,
                           db.records.c.review_timestamp, db.records.c.needs_review)
                    .where(and_(db.records.c.issue_id == issue_id, db.records.c.cache_source_id.is_(None)))
                    .order_by(db.records.c.severity.desc(), db.records.c.review_id).limit(limit))
    months = rows(select(func.substr(db.records.c.review_timestamp, 1, 7).label("month"), func.count().label("n"))
                  .where(db.records.c.issue_id == issue_id).group_by("month").order_by("month"))
    claims = rows(select(db.claims).where(db.claims.c.issue_id == issue_id))
    return {"issue": r[0], "severity_distribution": sev, "examples": examples, "monthly": months, "claims": claims}


@app.get("/api/trends")
def trends():
    return rows(select(db.trends).order_by(db.trends.c.month, db.trends.c.area))


@app.get("/api/memo")
def memo():
    m = doc("memo")
    if not m:
        raise HTTPException(404, "memo not loaded")
    return {"memo": m, "claims": rows(select(db.claims).order_by(db.claims.c.claim_id)),
            "facts": rows(select(db.facts).order_by(db.facts.c.fact_id))}


@app.get("/api/reviews")
def reviews(issue: str | None = None, topic: str | None = None, intent: str | None = None, q: str | None = None,
            min_severity: int = 1, limit: int = Query(25, le=200), offset: int = 0):
    c = db.records.c
    cond = [c.severity >= min_severity]
    if issue:
        cond.append(c.issue_id == issue)
    if topic:
        cond.append(c.topic == topic)
    if intent:
        cond.append(c.intent == intent)
    if q:
        cond.append(or_(c.evidence_quote.ilike(f"%{q}%"), c.review_id == q))
    total = rows(select(func.count()).select_from(db.records).where(and_(*cond)))[0]
    items = rows(select(db.records).where(and_(*cond)).order_by(c.severity.desc(), c.review_id).limit(limit).offset(offset))
    return {"total": list(total.values())[0], "items": items}


@app.get("/api/review/{review_id}")
def review(review_id: str):
    r = rows(select(db.records).where(db.records.c.review_id == review_id))
    if not r:
        raise HTTPException(404, "review not completed or unknown")
    return r[0]
