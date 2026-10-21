"""Stages 4-5 and record materialization.

materialize: one final record per source ID (completed / quarantined with reason) -> outputs/records.jsonl.gz
group:       code assigns each complaint/cancellation to issue "<topic>.<subtopic>" (saved membership);
             a model only names issues from a bounded evidence pack.
rank:        deterministic baseline priority = complaint_count x mean_severity = severity_sum. No model calls.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .common import RANKED_INTENTS, mean_string, read_jsonl, write_csv, write_json, write_jsonl
from .config import GROUP, prompt_text
from .enrich import cache_key
from .llm import now_iso
from .schema import GROUP_TOOL

AREA_OF_TOPIC = {"access": "access", "usability": "usability", "playback": "playback", "billing": "billing_support",
                 "support": "billing_support", "downloads": "downloads", "catalog": "catalog", "other": "other"}


def out_dir(store):
    d = store.dir / "outputs"
    d.mkdir(exist_ok=True)
    return d


def materialize(store, log=print):
    ck = cache_key()
    res = {r[0]: r for r in store.db.execute(
        "SELECT text_sha, status, rep_review_id, label_config, topic, subtopic, intent, sentiment, severity, entities, "
        "evidence_quote, needs_review, quarantine_reason, attempts, review_reason FROM results WHERE cache_key=?", (ck,))}
    fails = dict(store.db.execute("SELECT text_sha, last_error FROM failures WHERE cache_key=?", (ck,)))
    in_scope_text = {r[0] for r in store.db.execute("SELECT text_sha FROM texts WHERE in_scope=1")}
    counts = Counter()
    records, quarantine, enriched = [], [], []
    for rid, src_sha, tsha, empty, rating, ts, appv in store.db.execute(
            "SELECT review_id, source_sha256, text_sha, empty, review_rating, review_timestamp, app_version FROM source ORDER BY row_idx"):
        r = res.get(tsha)
        if empty:
            rec = {"review_id": rid, "source_sha256": src_sha, "status": "quarantined", "reason": "empty_review_text"}
        elif r and r[1] == "completed":
            rec = {"review_id": rid, "source_sha256": src_sha, "status": "completed", "topic": r[4], "intent": r[6],
                   "sentiment": r[7], "severity": r[8], "entities": json.loads(r[9]), "evidence_quote": r[10],
                   "needs_review": bool(r[11]), "label_config": r[3], "subtopic": r[5]}
            if rid != r[2]:
                rec["cache_source_id"] = r[2]
                counts["completed_by_exact_text_reuse"] += 1
            else:
                counts["completed_by_model_call"] += 1
            enriched.append([rid, ts, rating, appv, r[4], r[5], r[6], r[7], r[8], int(bool(r[11])), rec.get("cache_source_id", ""), r[3]])
        elif r and r[1] == "quarantined":
            rec = {"review_id": rid, "source_sha256": src_sha, "status": "quarantined", "reason": r[12], "attempts": r[13]}
        elif tsha in in_scope_text:
            reason = "unresolved_api_failure: " + fails[tsha][:120] if tsha in fails else "pending_not_processed"
            rec = {"review_id": rid, "source_sha256": src_sha, "status": "quarantined", "reason": reason}
        else:
            rec = {"review_id": rid, "source_sha256": src_sha, "status": "quarantined",
                   "reason": "outside_declared_classification_scope"}
        counts[rec["status"]] += 1
        if rec["status"] == "quarantined":
            counts["quarantine:" + rec["reason"].split(":")[0]] += 1
            quarantine.append(rec)
        records.append(rec)
    d = out_dir(store)
    write_jsonl(d / "records.jsonl.gz", records, gz=True)
    write_jsonl(d / "quarantine.jsonl.gz", quarantine, gz=True)
    with gzip.open(d / "enriched.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["review_id", "review_timestamp", "review_rating", "app_version", "topic", "subtopic", "intent",
                    "sentiment", "severity", "needs_review", "cache_source_id", "label_config"])
        w.writerows(enriched)
    summary = dict(sorted(counts.items()))
    summary["total_records"] = len(records)
    write_json(d / "record_summary.json", summary)
    log(f"materialize: {summary}")
    return summary


def load_records(path):
    return list(read_jsonl(path))


# ---------------------------------------------------------------------------------------------- grouping
def build_membership(records):
    members = defaultdict(list)
    for r in records:
        if r["status"] == "completed" and r["intent"] in RANKED_INTENTS:
            members[f"{r['topic']}.{r['subtopic']}"].append(r["review_id"])
    return members


def run_group(store, client, session_id, log=print):
    d = out_dir(store)
    records = load_records(d / "records.jsonl.gz")
    by_id = {r["review_id"]: r for r in records}
    members = build_membership(records)
    write_csv(d / "membership.csv", ["issue_id", "review_id"],
              [(iid, rid) for iid in sorted(members) for rid in members[iid]])
    # bounded evidence pack: up to 6 distinct quotes per issue (originals only, deterministic order)
    issues_payload = []
    for iid in sorted(members):
        ids = members[iid]
        sev = [by_id[x]["severity"] for x in ids]
        originals = sorted((x for x in ids if "cache_source_id" not in by_id[x]),
                           key=lambda x: hashlib.sha256(("group:" + x).encode()).hexdigest())
        seen, ev = set(), []
        for x in originals:
            q = by_id[x]["evidence_quote"][:220]
            if q not in seen:
                seen.add(q)
                ev.append({"review_id": x, "quote": q})
            if len(ev) == 6:
                break
        issues_payload.append({"issue_id": iid, "members": len(ids), "mean_severity": mean_string(sum(sev), len(sev)),
                               "sample": ev})
    system = prompt_text(GROUP.prompt_version)
    user = "Name each candidate issue.\nINPUT_JSON:\n" + json.dumps({"issues": issues_payload}, ensure_ascii=False)
    key = hashlib.sha256((GROUP.label_config + client.model_for(GROUP) + user).encode()).hexdigest()
    names = store.stage_cache_get(key)
    calls = []
    if names is None:
        lc = GROUP.label_config if client.provider != "fake" else f"{client.model_for(GROUP)}+group-v1+schema-v1"
        res = client.call_tool(GROUP, system, user, GROUP_TOOL, [], lc,
                               extra={"input_artifacts": ["outputs/membership.csv", "outputs/records.jsonl.gz (bounded sample)"]})
        calls = res.attempts
        items = (res.data or {}).get("items", []) if isinstance(res.data, dict) else []
        names = {}
        for it in items:
            if isinstance(it, dict) and it.get("issue_id") in members:
                names[it["issue_id"]] = {k: it.get(k) for k in ("name", "description", "coherent", "note")}
        with store.tx():
            store.add_calls(calls)
            store.stage_cache_put(key, "group", names, now_iso())
        log(f"group: model named {len(names)}/{len(members)} issues (1 call)")
    else:
        log("group: issue names reused from stage cache (0 calls)")
    issues = []
    for p in issues_payload:
        n = names.get(p["issue_id"], {})
        topic, sub = p["issue_id"].split(".", 1)
        issues.append({"issue_id": p["issue_id"], "topic": topic, "subtopic": sub, "area": AREA_OF_TOPIC[topic],
                       "name": n.get("name") or p["issue_id"], "description": n.get("description") or "",
                       "model_coherence_check": n.get("coherent"), "model_note": n.get("note") or "",
                       "member_count": p["members"], "evidence_sample": p["sample"],
                       "named_by": "model" if n else "code_fallback"})
    write_json(d / "issues.json", {"generated_at": now_iso(), "membership_rule": "issue_id = topic.subtopic of the completed "
                                   "complaint/cancellation record; one issue per review (allow_multi_issue=false)",
                                   "issues": issues})
    return issues


# ---------------------------------------------------------------------------------------------- ranking (no model)
def rank(records_path, membership_path, out, issues_path=None, enriched_path=None, log=print):
    out = Path(out)
    records = {r["review_id"]: r for r in read_jsonl(records_path)}
    pairs = []
    with open(membership_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pairs.append((row["issue_id"], row["review_id"]))
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate (issue_id, review_id) pairs in membership")
    if len({rid for _, rid in pairs}) != len(pairs):
        raise ValueError("a review belongs to more than one issue but allow_multi_issue=false")
    sev = defaultdict(list)
    canc = Counter()
    needs = Counter()
    for iid, rid in pairs:
        r = records[rid]
        if r["status"] != "completed" or r["intent"] not in RANKED_INTENTS:
            raise ValueError(f"membership contains non-ranked record {rid}")
        sev[iid].append(r["severity"])
        canc[iid] += r["intent"] == "cancellation"
        needs[iid] += bool(r["needs_review"])
    ranked_ids = {rid for _, rid in pairs}
    ungrouped = [rid for rid, r in records.items() if r["status"] == "completed" and r["intent"] in RANKED_INTENTS and rid not in ranked_ids]
    if ungrouped:
        raise ValueError(f"{len(ungrouped)} complaint/cancellation records lack an issue")
    rows = [{"issue_id": iid, "complaint_count": len(v), "severity_sum": sum(v), "mean_severity": mean_string(sum(v), len(v)),
             "priority_score": sum(v)} for iid, v in sev.items()]
    rows.sort(key=lambda x: (-x["priority_score"], x["issue_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    write_csv(out / "ranking.csv", ["rank", "issue_id", "complaint_count", "severity_sum", "mean_severity", "priority_score"],
              [[r["rank"], r["issue_id"], r["complaint_count"], r["severity_sum"], r["mean_severity"], r["priority_score"]] for r in rows])
    names = {}
    if issues_path and Path(issues_path).exists():
        names = {i["issue_id"]: i["name"] for i in json.loads(Path(issues_path).read_text())["issues"]}
    total_c = sum(r["complaint_count"] for r in rows)
    write_csv(out / "aggregates.csv", ["rank", "issue_id", "area", "issue_name", "complaint_count", "cancellation_count",
                                       "severity_sum", "mean_severity", "priority_score", "share_of_ranked_records_pct", "needs_review_count"],
              [[r["rank"], r["issue_id"], AREA_OF_TOPIC[r["issue_id"].split(".")[0]], names.get(r["issue_id"], ""),
                r["complaint_count"], canc[r["issue_id"]], r["severity_sum"], r["mean_severity"], r["priority_score"],
                pct(r["complaint_count"], total_c), needs[r["issue_id"]]] for r in rows])
    # product-area aggregates (secondary, explained separately from the issue baseline)
    area = defaultdict(lambda: Counter())
    completed = [r for r in records.values() if r["status"] == "completed"]
    for r in completed:
        a = AREA_OF_TOPIC[r["topic"]]
        area[a]["completed_records"] += 1
        if r["intent"] in RANKED_INTENTS:
            area[a]["complaint_count"] += 1
            area[a]["severity_sum"] += r["severity"]
            area[a]["cancellation_count"] += r["intent"] == "cancellation"
            area[a]["severity_4_plus"] += r["severity"] >= 4
    area_rows = []
    for a in ["access", "usability", "playback", "billing_support", "downloads", "catalog", "other"]:
        c = area[a]
        area_rows.append([a, c["completed_records"], c["complaint_count"], c["cancellation_count"], c["severity_sum"],
                          mean_string(c["severity_sum"], c["complaint_count"]) if c["complaint_count"] else "",
                          pct(c["complaint_count"], total_c), c["severity_4_plus"], pct(c["severity_4_plus"], c["complaint_count"])])
    area_rows.sort(key=lambda x: (-x[4], x[0]))
    write_csv(out / "area_aggregates.csv", ["area", "completed_records", "complaint_count", "cancellation_count", "severity_sum",
                                            "mean_severity", "share_of_ranked_records_pct", "severity_4_plus_count",
                                            "severity_4_plus_pct_of_area"], area_rows)
    # monthly trend: complaint share per area with denominators (first/last months are partial)
    if enriched_path and Path(enriched_path).exists():
        month_tot, month_area = Counter(), Counter()
        with gzip.open(enriched_path, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                m = row["review_timestamp"][:7]
                month_tot[m] += 1
                if row["intent"] in RANKED_INTENTS:
                    month_area[(m, AREA_OF_TOPIC[row["topic"]])] += 1
        trows = []
        for m in sorted(month_tot):
            for a in ["access", "usability", "playback", "billing_support", "downloads", "catalog", "other"]:
                trows.append([m, a, month_area[(m, a)], month_tot[m], pct(month_area[(m, a)], month_tot[m])])
        write_csv(out / "trends_monthly.csv", ["month", "area", "complaints", "completed_records_in_month",
                                               "complaint_share_pct"], trows)
    log(f"rank: {len(rows)} issues, {total_c:,} ranked complaint/cancellation records; top = "
        + ", ".join(f"{r['issue_id']}({r['priority_score']})" for r in rows[:3]))
    return rows


def pct(a, b):
    if not b:
        return ""
    return str((Decimal(a) * 100 / Decimal(b)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
