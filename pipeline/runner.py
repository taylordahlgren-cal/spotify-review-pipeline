"""Orchestrator: owns state, sessions/phases, budgets, stage order, stop conditions, checkpoints and logs."""
from __future__ import annotations

import importlib.util
import json
import shutil
import time
import uuid
from pathlib import Path

from . import analysis, memo, verify
from .common import FULL_ROWS, FULL_SHA256, read_json, write_json, write_jsonl
from .config import ENRICH, ENRICH_FALLBACK, GROUP, MEMO, ROOT, VERIFY, Limits, load_rates
from .enrich import cache_key, run_enrich
from .ingest import ingest
from .llm import BudgetExceeded, CallFailed, FatalAPIError, LLMClient, RateLimiter, SpendLedger, now_iso
from .store import Store

STAGES = ["ingest", "enrich", "verify", "materialize", "group", "rank", "memo"]


def snapshot(store, name):
    ids = store.completed_review_ids(cache_key())
    path = store.dir / "checkpoints" / f"{name}.json"
    write_json(path, {"completed_ids": ids, "count": len(ids), "taken_at": now_iso()})
    return len(ids)


def run(input_csv, state_dir, scope="all", provider="anthropic", limits: Limits | None = None, stages=None,
        run_id=None, log=print):
    limits = limits or Limits()
    stages = stages or STAGES
    store = Store(state_dir)
    prior = store.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    phase = "initial" if prior == 0 else "resume"
    session_n = prior + 1
    session_id = f"s{session_n:02d}-{uuid.uuid4().hex[:8]}"
    run_id = run_id or store.get("run_id") or f"run-{uuid.uuid4().hex[:10]}"
    store.set("run_id", store.get("run_id") or run_id)
    store.set("config", {"enrich": ENRICH.label_config, "enrich_fallback": ENRICH_FALLBACK.label_config,
                         "verify": VERIFY.label_config, "group": GROUP.label_config, "memo": MEMO.label_config,
                         "provider": provider})
    spent_before = store.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls").fetchone()[0]
    ledger = SpendLedger(limits.budget_usd, already_spent=spent_before)
    t_session = time.monotonic()
    started = now_iso()
    log(f"== session {session_n} ({phase}) run_id={run_id} provider={provider} workers={limits.workers} "
        f"budget=${limits.budget_usd} (already spent ${spent_before:.4f}) stages={','.join(stages)}")
    client = None
    stop_reason = "finished"
    stats = {}
    timings = {}

    def timed(stage, fn):
        t0 = time.monotonic()
        ts = now_iso()
        r = fn()
        dt = round(time.monotonic() - t0, 3)
        timings[stage] = dt
        store.stage_time(run_id, stage, ts, dt, {"session": session_id})
        return r

    start_count = None
    try:
        if "ingest" in stages:
            timed("ingest", lambda: ingest(store, input_csv, scope, log))
        if not store.get("ingest"):
            raise SystemExit("run the ingest stage first")
        # full ID snapshots: start of sessions 1-2 (2 = first resume = checkpoint_before) and the latest end
        start_count = snapshot(store, f"session-{session_n:02d}-start") if session_n <= 2 else len(store.completed_review_ids(cache_key()))
        store.db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (session_id, session_n, run_id, " ".join(stages), phase, started, None, None,
                          start_count, None, None, None))
        if any(s in stages for s in ("enrich", "verify", "group", "memo")):
            client = LLMClient(provider, ledger, RateLimiter(limits.requests_per_minute), load_rates(), limits,
                               run_id, session_id, phase)
        if "enrich" in stages:
            stats["enrich"] = timed("enrich", lambda: run_enrich(store, client, limits, session_id, log))
            sr = stats["enrich"]["stop_reason"]
            if sr != "finished":
                stop_reason = sr
        if stop_reason == "finished":
            if "verify" in stages:
                stats["verify"] = timed("verify", lambda: verify.run_verify(store, client, limits, session_id, log))
            if "materialize" in stages:
                stats["materialize"] = timed("materialize", lambda: analysis.materialize(store, log))
            if "group" in stages:
                timed("group", lambda: analysis.run_group(store, client, session_id, log))
            if "rank" in stages:
                o = store.dir / "outputs"
                timed("rank", lambda: analysis.rank(o / "records.jsonl.gz", o / "membership.csv", o, o / "issues.json",
                                                    o / "enriched.csv.gz", log))
            if "memo" in stages:
                stats["memo"] = timed("memo", lambda: memo.run_memo(store, client, session_id, log))
        else:
            log(f"stopping before downstream stages: {stop_reason}")
    except BudgetExceeded as e:
        stop_reason = f"budget: {e}"
        log(f"STOP: {stop_reason}")
    except (FatalAPIError, CallFailed) as e:
        if getattr(e, "attempts", None):
            with store.tx():
                store.add_calls(e.attempts)
        stop_reason = f"error: {e}"
        log(f"STOP: {stop_reason}")
    except KeyboardInterrupt:
        stop_reason = "hard_interrupt"
        log("STOP: hard interrupt; saved batches are kept")
    finally:
        end_count = snapshot(store, "latest-end") if start_count is not None else None
        wall = round(time.monotonic() - t_session, 3)
        store.db.execute("UPDATE sessions SET ended_at=?, stop_reason=?, completed_texts_end=?, ledger=?, wall_s=? "
                         "WHERE session_id=?", (now_iso(), stop_reason, end_count, json.dumps(ledger.snapshot()), wall, session_id))
        write_run_log(store)
        log(f"== session {session_n} ended: {stop_reason}; completed review IDs {start_count} -> {end_count}; "
            f"wall {wall}s; ledger {ledger.snapshot()}")
    return {"session_id": session_id, "phase": phase, "stop_reason": stop_reason, "timings": timings, "stats": stats,
            "ledger": ledger.snapshot(), "wall_s": wall}


def write_run_log(store):
    calls = store.calls()
    write_jsonl(store.dir / "run_log.jsonl", calls)
    sessions = [dict(zip(["session_id", "n", "run_id", "command", "phase", "started_at", "ended_at", "stop_reason",
                          "completed_ids_start", "completed_ids_end", "ledger", "wall_s"], r))
                for r in store.db.execute("SELECT * FROM sessions ORDER BY n")]
    by_role = {}
    for c in calls:
        b = by_role.setdefault(c["role"], {"attempts": 0, "succeeded": 0, "failed": 0, "synthetic_failures": 0,
                                           "input_tokens": 0, "uncached_input_tokens": 0, "cache_write_tokens": 0,
                                           "cache_read_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                                           "unknown_cost_attempts": 0, "models": set()})
        b["attempts"] += 1
        b[c["outcome"]] += 1
        b["synthetic_failures"] += bool(c.get("synthetic_failure"))
        for k in ("input_tokens", "uncached_input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens"):
            b[k] += c.get(k, 0)
        b["cost_usd"] += c.get("cost_usd", 0.0)
        b["unknown_cost_attempts"] += c.get("cost_status") == "unknown_possible_charge"
        b["models"].add(c["model"])
    for b in by_role.values():
        b["models"] = sorted(b["models"])
        b["cost_usd"] = round(b["cost_usd"], 6)
    stage_times = [dict(zip(["run_id", "stage", "started_at", "wall_s", "detail"], r))
                   for r in store.db.execute("SELECT * FROM stage_times")]
    ck = cache_key()
    status = dict(store.db.execute("SELECT status, COUNT(*) FROM results WHERE cache_key=? GROUP BY status", (ck,)).fetchall())
    summary = {"generated_at": now_iso(), "run_id": store.get("run_id"), "config": store.get("config"),
               "ingest": {k: v for k, v in (store.get("ingest") or {}).items() if k != "empty_text_review_ids"},
               "text_results": status,
               "pending_texts": store.db.execute("SELECT COUNT(*) FROM texts t LEFT JOIN results r ON r.text_sha=t.text_sha "
                                                 "AND r.cache_key=? WHERE t.in_scope=1 AND r.text_sha IS NULL", (ck,)).fetchone()[0],
               "texts_with_transport_failures": store.db.execute("SELECT COUNT(*) FROM failures").fetchone()[0],
               "calls_by_role": by_role, "total_cost_usd_from_usage": round(sum(b["cost_usd"] for b in by_role.values()), 6),
               "sessions": sessions, "stage_times": stage_times,
               "cost_basis": "cost_usd = usage tokens x cost/rates.csv (standard tier). Unknown-outcome attempts are listed, not priced."}
    write_json(store.dir / "run_summary.json", summary)
    return summary


def status(state_dir):
    store = Store(state_dir)
    return write_run_log(store)


def offline_rank(state_dir, log=print):
    o = Path(state_dir) / "outputs"
    return analysis.rank(o / "records.jsonl.gz", o / "membership.csv", o, o / "issues.json", o / "enriched.csv.gz", log)


CALL_FIELDS = ("request_id", "role", "review_ids", "model", "phase", "outcome", "label_config", "input_tokens", "output_tokens")


def export_grading(state_dir, input_csv, out="grading", log=print):
    store = Store(state_dir)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    o = store.dir / "outputs"
    ing = store.get("ingest")
    full = ing["input_sha256"] == FULL_SHA256
    run = {"version": "a5-audit-v1", "analysis_count": ing["rows"], "analysis_sha256": ing["input_sha256"],
           "classification_input_fields": ["review_text"], "allow_multi_issue": False,
           "run_id": store.get("run_id"), "declared_classification_scope": ing["scope"],
           "scope_detail": ing["scope_detail"], "label_configs": store.get("config"),
           "full_corpus_input": full, "exported_at": now_iso()}
    write_json(out / "run.json", run)
    spec = importlib.util.spec_from_file_location("check_submission", ROOT / "check_submission.py")
    cs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cs)
    cs.write_json(out / "ingestion.json", cs.profile(input_csv))
    for name in ("records.jsonl", "calls.jsonl"):
        for p in (out / name, out / (name + ".gz")):
            p.unlink(missing_ok=True)
    shutil.copyfile(o / "records.jsonl.gz", out / "records.jsonl.gz")
    for name in ("membership.csv", "ranking.csv", "claims.csv"):
        shutil.copyfile(o / name, out / name)
    # final label_config per completed original record, to separate rejected outputs from accepted ones in the log
    final_lc = {}
    import gzip as _gz
    with _gz.open(o / "records.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["status"] == "completed" and "cache_source_id" not in r:
                final_lc[r["review_id"]] = r["label_config"]
    calls = []
    for c in store.calls():
        if c["role"] == "enrich" and c["outcome"] == "succeeded":
            # A request can succeed while the output for some reviews fails validation; those reviews were then
            # re-sent (retry or capped fallback). Log the rejected part as its own failed entry so every completed
            # review's successful entry carries the configuration that actually produced its label.
            rejected = [i for i in c["review_ids"] if i in final_lc and final_lc[i] != c["label_config"]]
            if rejected:
                kept = [i for i in c["review_ids"] if i not in rejected]
                if kept:
                    calls.append({"request_id": c["request_id"] + ":rejected-output", "role": "enrich",
                                  "review_ids": rejected, "model": c["model"], "phase": c["phase"], "outcome": "failed",
                                  "label_config": c["label_config"], "input_tokens": 0, "output_tokens": 0,
                                  "error": "output for these reviews failed validation in this request; usage is counted "
                                           "on the parent entry", "parent_request_id": c["request_id"],
                                  "run_id": c.get("run_id"), "session_id": c.get("session_id")})
                    c = {**c, "review_ids": kept}
                else:
                    c = {**c, "outcome": "failed", "error": "output failed validation for every review in this request "
                                                            "(HTTP request succeeded; usage is real)"}
        calls.append({**{k: c.get(k) for k in CALL_FIELDS},
                      **{k: c.get(k) for k in ("run_id", "session_id", "attempt", "uncached_input_tokens", "cache_write_tokens",
                                               "cache_read_tokens", "cost_usd", "cost_status", "error", "synthetic_failure",
                                               "prompt_version", "effort", "thinking", "started_at", "wall_s", "stop_reason",
                                               "input_artifacts", "invalid_reasons", "validation_attempt") if k in c}})
    write_jsonl(out / "calls.jsonl", calls)
    sessions = [r[0] for r in store.db.execute("SELECT n FROM sessions WHERE phase='resume' ORDER BY n")]
    cps = store.dir / "checkpoints"
    if sessions:
        before = read_json(cps / f"session-{sessions[0]:02d}-start.json")
        last = store.db.execute("SELECT MAX(n) FROM sessions").fetchone()[0]
        after = read_json(cps / "latest-end.json")
        write_json(out / "checkpoint_before.json", {"completed_ids": before["completed_ids"], "taken_at": before["taken_at"],
                                                    "note": f"start of first resume session {sessions[0]}"})
        write_json(out / "checkpoint_after.json", {"completed_ids": after["completed_ids"], "taken_at": after["taken_at"],
                                                   "note": f"end of session {last}"})
    else:
        log("export: WARNING no resume session yet; checkpoint files not written")
    log(f"export: wrote {out}/ (records, {len(calls)} calls, scope {ing['scope']}, full_corpus_input={full})")
    return run
