"""Load saved pipeline outputs into the dashboard database (no model calls).

    DATABASE_URL=postgresql://... python -m dashboard.load_db --state runs/final
    python -m dashboard.load_db --state runs/final          # local sqlite: dashboard/dashboard.db
"""
import argparse
import csv
import gzip
import json
from pathlib import Path

from sqlalchemy import insert

from . import db

ROOT = Path(__file__).resolve().parent.parent


def rd_csv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def maybe_json(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--evals", default=str(ROOT / "evals"))
    ap.add_argument("--cost", default=str(ROOT / "cost"))
    a = ap.parse_args()
    try:  # DATABASE_URL may live in the project's .env (never committed)
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    state = Path(a.state)
    o = state / "outputs"
    eng = db.engine()
    db.meta.drop_all(eng)
    db.meta.create_all(eng)
    membership = {r["review_id"]: r["issue_id"] for r in rd_csv(o / "membership.csv")}
    meta = {}
    with gzip.open(o / "enriched.csv.gz", "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            meta[r["review_id"]] = r
    rows, n = [], 0
    with eng.begin() as con:
        with gzip.open(o / "records.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["status"] != "completed":
                    continue
                m = meta.get(r["review_id"], {})
                rows.append({"review_id": r["review_id"], "review_timestamp": m.get("review_timestamp"),
                             "review_rating": m.get("review_rating"), "app_version": m.get("app_version"),
                             "topic": r["topic"], "subtopic": r.get("subtopic"), "intent": r["intent"],
                             "sentiment": r["sentiment"], "severity": r["severity"], "needs_review": r["needs_review"],
                             "evidence_quote": r["evidence_quote"][:600], "cache_source_id": r.get("cache_source_id"),
                             "label_config": r["label_config"], "issue_id": membership.get(r["review_id"])})
                if len(rows) == 5000:
                    con.execute(insert(db.records), rows)
                    n += len(rows)
                    rows = []
        if rows:
            con.execute(insert(db.records), rows)
            n += len(rows)
        iss = {i["issue_id"]: i for i in json.loads((o / "issues.json").read_text())["issues"]}
        con.execute(insert(db.issues), [{
            "issue_id": r["issue_id"], "rank": int(r["rank"]), "area": r["area"], "name": iss[r["issue_id"]]["name"],
            "description": iss[r["issue_id"]]["description"], "complaint_count": int(r["complaint_count"]),
            "cancellation_count": int(r["cancellation_count"]), "severity_sum": int(r["severity_sum"]),
            "mean_severity": r["mean_severity"], "priority_score": int(r["priority_score"]),
            "share_pct": r["share_of_ranked_records_pct"], "needs_review_count": int(r["needs_review_count"]),
            "model_coherent": iss[r["issue_id"]].get("model_coherence_check"), "model_note": iss[r["issue_id"]].get("model_note")}
            for r in rd_csv(o / "aggregates.csv")])
        con.execute(insert(db.areas), [{
            "area": r["area"], "completed_records": int(r["completed_records"]), "complaint_count": int(r["complaint_count"]),
            "cancellation_count": int(r["cancellation_count"]), "severity_sum": int(r["severity_sum"]),
            "mean_severity": r["mean_severity"], "share_pct": r["share_of_ranked_records_pct"],
            "severity_4_plus": int(r["severity_4_plus_count"]), "severity_4_plus_pct": r["severity_4_plus_pct_of_area"]}
            for r in rd_csv(o / "area_aggregates.csv")])
        if (o / "trends_monthly.csv").exists():
            con.execute(insert(db.trends), [{"month": r["month"], "area": r["area"], "complaints": int(r["complaints"]),
                                             "completed_in_month": int(r["completed_records_in_month"]),
                                             "share_pct": r["complaint_share_pct"]} for r in rd_csv(o / "trends_monthly.csv")])
        cited = {r["claim_id"] for r in rd_csv(o / "claims.csv")}
        con.execute(insert(db.claims), [{**r, "cited_in_memo": r["claim_id"] in cited} for r in rd_csv(o / "claims_all.csv")])
        pack = json.loads((o / "memo_input_pack.json").read_text())
        con.execute(insert(db.facts), [{"fact_id": f["fact_id"], "scope": f.get("area", "coverage"), "metric": f["metric"],
                                        "value": f["value"]} for f in pack["area_facts"] + pack["coverage_facts"]])
        docs = {"memo": maybe_json(o / "memo.json"), "record_summary": maybe_json(o / "record_summary.json"),
                "run_summary": maybe_json(state / "run_summary.json"), "ingestion": maybe_json(state / "ingestion_report.json"),
                "verification": maybe_json(state / "verification_report.json"),
                "golden": maybe_json(Path(a.evals) / "golden_results.json"),
                "planted": maybe_json(Path(a.evals) / "planted_error_test.json"),
                "injection": maybe_json(Path(a.evals) / "injection_test.json"),
                "cost": maybe_json(Path(a.cost) / "replay_result.json")}
        if docs["run_summary"]:
            docs["run_summary"].pop("stage_times", None)
        if docs["ingestion"]:
            docs["ingestion"].pop("empty_text_review_ids", None)
        if docs["injection"]:
            docs["injection"].pop("calls", None)
        con.execute(insert(db.documents), [{"key": k, "body": v} for k, v in docs.items() if v is not None])
    print(f"loaded {n:,} completed records, {len(iss)} issues into {eng.url.render_as_string(hide_password=True)}")


if __name__ == "__main__":
    main()
