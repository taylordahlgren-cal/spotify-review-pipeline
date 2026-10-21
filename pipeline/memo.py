"""Stage 6 - Recommend. The memo agent receives only saved aggregates and a bounded evidence pack. Code checks that every
number, claim ID, issue ID and review ID in the memo exists in the pack; one retry with feedback, then flag for review."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from .common import read_json, read_jsonl, write_csv, write_json
from .config import MEMO, prompt_text
from .llm import now_iso
from .schema import MEMO_TOOL

METRICS = ("complaint_count", "severity_sum", "mean_severity", "priority_score")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
CITE_RE = re.compile(r"\[([A-Z]\d{2,3}(?:\s*,\s*[A-Z]\d{2,3})*)\]")
NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_pack(outputs: Path, top_n=10, evidence_issues=6, quotes_per_issue=3):
    ranking = _read_csv(outputs / "ranking.csv")
    aggregates = {r["issue_id"]: r for r in _read_csv(outputs / "aggregates.csv")}
    areas = _read_csv(outputs / "area_aggregates.csv")
    issues = {i["issue_id"]: i for i in read_json(outputs / "issues.json")["issues"]}
    summary = read_json(outputs / "record_summary.json")
    claims, rank_rows = [], []
    n = 0
    for r in ranking[:top_n]:
        ids = {}
        for m in METRICS:
            n += 1
            cid = f"C{n:02d}"
            claims.append({"claim_id": cid, "issue_id": r["issue_id"], "metric": m, "value": r[m]})
            ids[m] = cid
        a = aggregates[r["issue_id"]]
        rank_rows.append({"rank": int(r["rank"]), "issue_id": r["issue_id"], "issue_name": issues[r["issue_id"]]["name"],
                          "description": issues[r["issue_id"]]["description"],
                          "complaint_count": r["complaint_count"], "severity_sum": r["severity_sum"],
                          "mean_severity": r["mean_severity"], "priority_score": r["priority_score"], "claims": ids,
                          "cancellation_count_info": a["cancellation_count"]})
    facts, t = [], 0
    for a in areas:
        for metric in ("complaint_count", "cancellation_count", "severity_sum", "mean_severity",
                       "share_of_ranked_records_pct", "severity_4_plus_pct_of_area"):
            if a[metric] == "":
                continue
            t += 1
            facts.append({"fact_id": f"T{t:02d}", "area": a["area"], "metric": metric, "value": a[metric]})
    k = 0
    coverage = []
    for key in ("total_records", "completed", "quarantined", "completed_by_model_call", "completed_by_exact_text_reuse",
                "quarantine:outside_declared_classification_scope", "quarantine:empty_review_text",
                "quarantine:invalid_model_output", "quarantine:unresolved_api_failure", "quarantine:pending_not_processed"):
        if key in summary:
            k += 1
            coverage.append({"fact_id": f"K{k:02d}", "metric": key, "value": str(summary[key])})
    evidence = []
    for r in ranking[:evidence_issues]:
        for e in issues[r["issue_id"]]["evidence_sample"][:quotes_per_issue]:
            evidence.append({"issue_id": r["issue_id"], "review_id": e["review_id"], "quote": e["quote"]})
    pack = {"question": "Where should the next quarter of product effort go: access, usability, playback, or billing/support?",
            "baseline_rule": "priority_score = complaint_count x mean_severity = severity_sum over complaint+cancellation records; "
                             "ties by issue_id", "coverage_facts": coverage, "area_facts": facts, "ranking": rank_rows,
            "evidence": evidence,
            "notes": ["Areas: billing_support combines topics billing and support.",
                      "share_of_ranked_records_pct = area complaints / all complaint+cancellation records x 100.",
                      "Records include exact-text reuse: duplicate texts carry one shared model label (cache_source_id)."]}
    return pack, claims


def allowed_numbers(pack):
    vals = set()
    def add(v):
        s = str(v).replace(",", "")
        vals.add(s)
        try:
            f = float(s)
            vals.add(f"{f:g}")
            if "." in s:
                vals.add(s.rstrip("0").rstrip("."))
                vals.add(f"{f:.1f}")
                vals.add(f"{f:.2f}")
        except ValueError:
            pass
    for r in pack["ranking"]:
        for m in METRICS + ("rank", "cancellation_count_info"):
            add(r[m])
    for f in pack["area_facts"] + pack["coverage_facts"]:
        add(f["value"])
    return vals


def check_memo(memo: dict, pack: dict):
    problems = []
    claim_ids = {c for r in pack["ranking"] for c in r["claims"].values()}
    fact_ids = {f["fact_id"] for f in pack["area_facts"] + pack["coverage_facts"]}
    issue_ids = {r["issue_id"] for r in pack["ranking"]}
    all_issue_ids = issue_ids | {e["issue_id"] for e in pack["evidence"]}
    review_ids = {e["review_id"] for e in pack["evidence"]}
    nums = allowed_numbers(pack)
    texts = [memo.get("title", ""), memo.get("recommendation", "")]
    for s in memo.get("supporting_evidence", []):
        texts.append(s.get("point", ""))
        problems += [f"unknown claim {c}" for c in s.get("claim_ids", []) if c not in claim_ids | fact_ids]
        problems += [f"unknown issue {i}" for i in s.get("issue_ids", []) if i not in all_issue_ids]
        problems += [f"unknown review {i}" for i in s.get("review_ids", []) if i not in review_ids]
    for a in memo.get("alternatives", []):
        texts.append(a.get("assessment", ""))
        problems += [f"unknown claim {c}" for c in a.get("claim_ids", []) if c not in claim_ids | fact_ids]
    for d in memo.get("dashboard_recommendations", []):
        texts += [d.get("title", ""), d.get("detail", "")]
        problems += [f"unknown claim {c}" for c in d.get("claim_ids", []) if c not in claim_ids | fact_ids]
        problems += [f"unknown issue {i}" for i in d.get("issue_ids", []) if i not in all_issue_ids]
    texts += memo.get("limitations", [])
    cited = set()
    for t in texts:
        for tag in re.findall(r"\[([^\]]*)\]", t):  # every bracketed tag must be a list of known IDs
            parts = [x.strip() for x in tag.split(",")]
            if not all(re.fullmatch(r"[A-Z]\d{2,3}", x) and x in claim_ids | fact_ids for x in parts):
                problems.append(f"invalid bracket tag [{tag}]")
        for m in CITE_RE.finditer(t):
            for c in re.split(r"\s*,\s*", m.group(1)):
                cited.add(c)
                if c not in claim_ids | fact_ids:
                    problems.append(f"unknown citation [{c}]")
        for u in UUID_RE.findall(t):
            if u not in review_ids:
                problems.append(f"unknown review id {u}")
        stripped = UUID_RE.sub(" ", CITE_RE.sub(" ", t))
        for iid in re.findall(r"\b[a-z_]+\.[a-z_]+\b", stripped):
            if iid.split(".")[0] in {"access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"} \
                    and iid not in all_issue_ids:
                problems.append(f"unknown issue id {iid}")
        stripped = re.sub(r"\b[a-z_]+\.[a-z_]+\b", " ", stripped)
        for num in NUM_RE.findall(stripped):
            v = num.rstrip("%").replace(",", "")
            if v not in nums:
                problems.append(f"number not in facts pack: {num}")
    return sorted(set(problems)), sorted(cited)


def render_md(memo, pack, claims_by_id, check, meta):
    def cites(ids):
        return ", ".join(ids) if ids else ""
    lines = [f"# {memo['title']}", "",
             f"*Generated {meta['generated_at']} by `{meta['model']}` (prompt `{MEMO.prompt_version}`) from saved aggregates only. "
             f"Automated claim check: **{check['status']}**. Numbers carry claim IDs ([C..] = issue-level, checked in "
             f"`claims.csv`; [T..] = product-area facts in `area_aggregates.csv`; [K..] = coverage).*", "",
             f"**Recommended priority area:** `{memo['recommended_area']}`", "", memo["recommendation"], "",
             "## Supporting evidence", ""]
    for s in memo["supporting_evidence"]:
        extra = []
        if s.get("issue_ids"):
            extra.append("issues " + ", ".join(f"`{i}`" for i in s["issue_ids"]))
        if s.get("review_ids"):
            extra.append("reviews " + ", ".join(f"`{i}`" for i in s["review_ids"]))
        lines.append(f"- {s['point']}" + (f" ({'; '.join(extra)})" if extra else ""))
    lines += ["", "## Alternatives considered", ""]
    for a in memo["alternatives"]:
        lines.append(f"- **{a['area']}** - {a['assessment']}")
    lines += ["", "## Recommended actions", ""]
    for d in memo["dashboard_recommendations"]:
        lines.append(f"- **{d['title']}** - {d['detail']}")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in memo["limitations"]]
    lines += ["", "## Baseline ranking used (top 10)", "", "| Rank | Issue | Name | Complaints | Severity sum | Mean severity | Priority |",
              "|---|---|---|---|---|---|---|"]
    for r in pack["ranking"]:
        c = r["claims"]
        lines.append(f"| {r['rank']} | `{r['issue_id']}` | {r['issue_name']} | {r['complaint_count']} [{c['complaint_count']}] | "
                     f"{r['severity_sum']} [{c['severity_sum']}] | {r['mean_severity']} [{c['mean_severity']}] | "
                     f"{r['priority_score']} [{c['priority_score']}] |")
    lines += ["", f"Claim check problems: {check['problems'] or 'none'}", ""]
    return "\n".join(lines)


def run_memo(store, client, session_id, log=print):
    outputs = store.dir / "outputs"
    pack, claims = build_pack(outputs)
    write_json(outputs / "memo_input_pack.json", pack)
    system = prompt_text(MEMO.prompt_version)
    base_user = "Write the memo from this facts pack.\nINPUT_JSON:\n" + json.dumps(pack, ensure_ascii=False)
    model = client.model_for(MEMO)
    key = hashlib.sha256((MEMO.label_config + model + base_user).encode()).hexdigest()
    cached = store.stage_cache_get(key)
    lc = MEMO.label_config if client.provider != "fake" else f"{model}+memo-v1+schema-v1"
    if cached and cached["memo"] and not check_memo(cached["memo"], pack)[0]:
        memo, problems, cited, attempts_used = cached["memo"], cached["problems"], cached["cited"], cached["attempts"]
        log("memo: reused from stage cache (0 calls; re-checked)")
    else:
        if cached:
            log("memo: cached memo fails the current claim check; regenerating")
        user = base_user
        memo, problems, cited = None, ["no output"], []
        attempts_used = 0
        for attempt in (1, 2):
            attempts_used = attempt
            res = client.call_tool(MEMO, system, user, MEMO_TOOL, [], lc,
                                   extra={"input_artifacts": ["outputs/ranking.csv", "outputs/aggregates.csv",
                                                              "outputs/area_aggregates.csv", "outputs/issues.json",
                                                              "outputs/memo_input_pack.json"], "validation_attempt": attempt})
            with store.tx():
                store.add_calls(res.attempts)
            memo = res.data if isinstance(res.data, dict) else None
            if not memo or any(k not in memo for k in MEMO_TOOL["input_schema"]["required"]):
                problems = ["missing memo fields"]
            else:
                problems, cited = check_memo(memo, pack)
            if not problems:
                break
            log(f"memo: attempt {attempt} failed checks: {problems[:8]}")
            user = base_user + "\n\nYour previous memo failed the automated check:\n- " + "\n- ".join(problems[:30]) + \
                "\nRewrite it fixing every problem. Use only numbers and IDs from the pack, each followed by its [ID]."
        with store.tx():
            store.stage_cache_put(key, "memo", {"memo": memo, "problems": problems, "cited": cited, "attempts": attempts_used}, now_iso())
    status = "pass" if not problems else "failed_needs_human_review"
    check = {"status": status, "problems": problems, "cited_ids": cited, "attempts": attempts_used}
    claims_by_id = {c["claim_id"]: c for c in claims}
    cited_claims = [c for c in claims if c["claim_id"] in cited]
    if not cited_claims:  # always export the top issue's checked numbers
        cited_claims = [c for c in claims if c["issue_id"] == pack["ranking"][0]["issue_id"]]
    write_csv(outputs / "claims.csv", ["claim_id", "issue_id", "metric", "value"],
              [[c["claim_id"], c["issue_id"], c["metric"], c["value"]] for c in cited_claims])
    write_csv(outputs / "claims_all.csv", ["claim_id", "issue_id", "metric", "value"],
              [[c["claim_id"], c["issue_id"], c["metric"], c["value"]] for c in claims])
    meta = {"generated_at": now_iso(), "model": model}
    write_json(outputs / "memo.json", {"memo": memo, "check": check, "meta": meta})
    if memo:
        (outputs / "memo.md").write_text(render_md(memo, pack, claims_by_id, check, meta), encoding="utf-8")
    log(f"memo: check {status}; cited {len(cited)} IDs; claims.csv rows {len(cited_claims)}")
    return check
