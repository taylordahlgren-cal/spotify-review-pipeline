"""100-review cost and runtime calculator.

OFFLINE REPLAY (default; no API key, no model calls):
    python -m cost.calculator                      # == replay
    python -m cost.calculator replay --rate-multiplier 2      # check: API subtotal doubles, time/local cost unchanged
    python -m cost.calculator replay --rates cost/rates.csv --assumptions cost/assumptions.json \
        --refresh 500=runs/dev500/run_log.jsonl --refresh 10k=runs/final/run_log.jsonl

PAID PILOT (explicit; needs ANTHROPIC_API_KEY in .env):
    python -m cost.calculator pilot --execute

Importing this module never makes a call.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

ITEMS = ("uncached_input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens")
ITEM_RATE = {"uncached_input_tokens": "input", "cache_write_tokens": "cache_write_5m", "cache_read_tokens": "cache_read",
             "output_tokens": "output"}


def load_rates(path, multiplier=1.0):
    rates, meta = {}, {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["processing_tier"] != "standard":
                continue
            rates.setdefault(row["model"], {})[row["billing_item"]] = float(row["usd_per_million"]) * multiplier
            meta[(row["model"], row["billing_item"])] = row
    return rates, meta


def read_jsonl(p):
    p = Path(p)
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def price_calls(calls, rates):
    """usage rows: one per call x billing item. item_cost = billed_units x price_per_unit (per-million / 1e6)."""
    rows = []
    for c in calls:
        for item in ITEMS:
            units = int(c.get(item) or 0)
            per_m = rates.get(c["model"], {}).get(ITEM_RATE[item])
            if per_m is None:
                cost, status = None, "unknown_rate"
            else:
                cost, status = units * (per_m / 1_000_000), "priced_from_actual_usage"
            if c.get("cost_status") == "unknown_possible_charge":
                status = "unknown_possible_charge_usage_unavailable"
            rows.append({"run_id": c["run_id"], "request_id": c["request_id"], "role": c["role"], "model": c["model"],
                         "outcome": c["outcome"], "attempt": c.get("attempt"), "billing_item": ITEM_RATE[item],
                         "billed_units": units, "unit": "token", "usd_per_million": per_m,
                         "item_cost_usd": round(cost, 10) if cost is not None else None, "status": status})
    return rows


def stage_stats(calls, usage_rows):
    cost_by_req = defaultdict(float)
    for u in usage_rows:
        cost_by_req[u["request_id"]] += u["item_cost_usd"] or 0.0
    out = {}
    for c in calls:
        s = out.setdefault(c["role"], Counter())
        s["attempts"] += 1
        s["succeeded"] += c["outcome"] == "succeeded"
        s["failed"] += c["outcome"] == "failed"
        s["synthetic_failures"] += bool(c.get("synthetic_failure"))
        s["retry_attempts"] += (c.get("attempt") or 1) > 1 or (c.get("validation_attempt") or 1) > 1
        s["fallback_calls"] += c["role"] == "enrich" and "sonnet" in c["model"]
        s["reviews_sent"] += len(c.get("review_ids") or [])
        for item in ITEMS:
            s[item] += int(c.get(item) or 0)
        s["cost_usd_x1e10"] += round(cost_by_req[c["request_id"]] * 1e10)
        s["summed_call_seconds_x1000"] += round((c.get("wall_s") or 0) * 1000)
    res = {}
    for role, s in out.items():
        d = dict(s)
        d["cost_usd"] = d.pop("cost_usd_x1e10") / 1e10
        d["summed_call_seconds"] = d.pop("summed_call_seconds_x1000") / 1000
        res[role] = d
    return res


def measure_enrich(calls, rates):
    """Per-distinct-text unit economics from enrichment calls in a log (used for 100 / 500 / 10k refreshes)."""
    enr = [c for c in calls if c["role"] == "enrich"]
    if not enr:
        return None
    rows = price_calls(enr, rates)
    cost = sum(r["item_cost_usd"] or 0 for r in rows)
    first_pass = [c for c in enr if (c.get("validation_attempt") or 1) == 1 and c["outcome"] == "succeeded"]
    texts = sum(len(c["review_ids"]) for c in first_pass)
    tok = {i: sum(int(c.get(i) or 0) for c in enr) for i in ITEMS}
    retried = sum(len(c["review_ids"]) for c in enr if (c.get("validation_attempt") or 1) == 2 and c["outcome"] == "succeeded")
    return {"enrich_attempts": len(enr), "first_pass_requests": len(first_pass), "texts_first_pass": texts,
            "texts_retried": retried,
            "failed_attempts": sum(c["outcome"] == "failed" for c in enr),
            "retry_or_split_requests": sum((c.get("validation_attempt") or 1) == 2 for c in enr),
            "fallback_requests": sum("sonnet" in c["model"] for c in enr),
            "cost_usd": cost, "cost_per_text": cost / texts if texts else None,
            "tokens_per_text": {i: (tok[i] / texts if texts else None) for i in ITEMS},
            "summed_call_seconds": sum(c.get("wall_s") or 0 for c in enr),
            "call_seconds_per_text": (sum(c.get("wall_s") or 0 for c in enr) / texts) if texts else None}


def fallback_cost_per_text(rates):
    # Estimate (labelled): one single-review Sonnet call = prompt + tool schema + one review in, ~120 tokens out.
    from pipeline.config import ENRICH_FALLBACK, prompt_text
    from pipeline.schema import ENRICH_TOOL
    tokens_in = (len(prompt_text("enrich-v1")) + len(json.dumps(ENRICH_TOOL))) / 3.5 + 60
    r = rates.get(ENRICH_FALLBACK.model)
    return (tokens_in * r["input"] + 120 * r["output"]) / 1e6, tokens_in


def project(m, stages, runs, assumptions, rates):
    """Base and conservative scenarios. Each stage extrapolates from its own work count; fixed overhead added once."""
    a = assumptions
    cold = runs["cold"]
    texts_measured = m["texts_first_pass"]
    # retry rate = share of texts that needed a second request (measured cost/time per text already include them)
    retry_rate = m.get("texts_retried", 0) / max(1, texts_measured)
    fail_rate = m["failed_attempts"] / max(1, m["enrich_attempts"])
    fb_cost, fb_tokens = fallback_cost_per_text(rates)
    fb_rate_measured = m["fallback_requests"] / max(1, texts_measured)
    v = stages.get("verify", {})
    v_cost_per_text = v.get("cost_usd", 0) / max(1, v.get("reviews_sent", 1)) if v else 0
    fixed = sum(stages.get(r, {}).get("cost_usd", 0) for r in ("group", "memo"))
    sec_per_text = cold["stage_wall_s"].get("enrich", 0) / max(1, texts_measured)  # 1 worker, wall clock
    fixed_s = sum(cold["stage_wall_s"].get(s, 0) for s in ("group", "memo", "rank"))
    out = []
    for sc in a["scenarios"]:
        n = sc["texts_to_classify"]
        rows = {}
        for case in ("base", "conservative"):
            cons = case == "conservative"
            rr = max(a["conservative"]["min_retry_rate"], retry_rate * a["conservative"]["retry_rate_multiplier"]) if cons else retry_rate
            infl = a["conservative"]["output_token_inflation"] if cons else 1.0
            fb = a["conservative"]["fallback_fraction"] if cons else fb_rate_measured
            out_share = (m["tokens_per_text"]["output_tokens"] * rates["claude-haiku-5-5"]["output"] / 1e6) / m["cost_per_text"] \
                if m["cost_per_text"] else 0
            unit = m["cost_per_text"] * (1 - out_share + out_share * infl)
            # base: measured unit cost already contains measured retries/fallbacks; conservative adds extra retries
            # (each costing roughly one more first-pass share) and the full fallback quota at Sonnet prices
            extra_rr = max(0.0, rr - retry_rate)
            enrich_cost = n * unit * (1 + extra_rr) + (n * max(0.0, fb - fb_rate_measured) * fb_cost if cons else 0.0)
            n_ver = a["verify_max"] if (cons and a["conservative"]["verify_at_max"]) else min(a["verify_max"], round(a["verify_fraction"] * n))
            verify_cost = n_ver * v_cost_per_text * (1 + extra_rr)
            api = enrich_cost + verify_cost + fixed
            workers = a["max_workers"]
            t_workers = n * sec_per_text * (1 + extra_rr) / (workers * a["parallel_efficiency"])
            t_rpm = (n / 50) * (1 + rr) / a["requests_per_minute_limit"] * 60
            enrich_s = max(t_workers, t_rpm)
            ver_s = n_ver * sec_per_text
            total_s = enrich_s + ver_s / max(1, workers * a["parallel_efficiency"]) + fixed_s + n / 20000  # + ingest/materialize
            local = total_s / 3600 * a["local_compute_usd_per_hour"]
            rows[case] = {"retry_rate": round(rr, 4), "fallback_fraction": round(fb, 4), "enrich_usd": round(enrich_cost, 2),
                          "verify_reviews": n_ver, "verify_usd": round(verify_cost, 2), "fixed_group_memo_usd": round(fixed, 4),
                          "api_total_usd": round(api, 2), "local_compute_usd_estimate": round(local, 4),
                          "elapsed_hours": round(total_s / 3600, 2), "binding_limit": "rpm" if t_rpm > t_workers else "workers",
                          "throughput_texts_per_min": round(n / (enrich_s / 60), 1) if enrich_s else None,
                          "over_budget": api > a["budget_usd"]}
        out.append({"scenario": sc["name"], "texts_to_classify": n, "rows_accounted": sc["rows"], **rows})
    return out, {"retry_rate_measured": retry_rate, "failed_attempt_rate": fail_rate, "fallback_cost_per_text_estimate": fb_cost,
                 "fallback_prompt_tokens_estimate": round(fb_tokens), "fallback_rate_measured": fb_rate_measured,
                 "verify_cost_per_text": v_cost_per_text, "fixed_overhead_usd": fixed, "seconds_per_text_1_worker": sec_per_text}


def fmt(x, nd=6):
    return "n/a" if x is None else (f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}")


def replay(args):
    rates, meta = load_rates(args.rates, args.rate_multiplier)
    assumptions = json.loads(Path(args.assumptions).read_text())
    calls = read_jsonl(HERE / "pilot_calls.jsonl")
    runs = json.loads((HERE / "pilot_runs.json").read_text())
    records = read_jsonl(HERE / "pilot_records.jsonl")
    usage = price_calls(calls, rates)
    with open(HERE / ("usage.csv" if args.rate_multiplier == 1 else f"usage_x{args.rate_multiplier:g}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(usage[0].keys()))
        w.writeheader()
        w.writerows(usage)
    per_run = {}
    for name, r in runs.items():
        rc = [c for c in calls if c["run_id"] == r["run_id"]]
        ru = [u for u in usage if u["run_id"] == r["run_id"]]
        st = stage_stats(rc, ru)
        api = sum(u["item_cost_usd"] or 0 for u in ru)
        per_run[name] = {"stages": st, "api_usd": api, "wall_s": r["wall_s"],
                         "local_usd": r["wall_s"] / 3600 * assumptions["local_compute_usd_per_hour"]}
    m = measure_enrich([c for c in calls if c["run_id"] == runs["cold"]["run_id"]], rates)
    proj, unit = project(m, per_run["cold"]["stages"], runs, assumptions, rates)
    refreshes = {}
    for spec in args.refresh or []:
        label, path = spec.split("=", 1)
        if Path(path).exists():
            refreshes[label] = measure_enrich(read_jsonl(path), rates)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rate_multiplier": args.rate_multiplier,
              "rates_file": str(args.rates), "per_run": per_run, "enrich_unit": m, "unit_assumptions": unit,
              "projections": proj, "refreshes": refreshes, "assumptions": assumptions}
    suffix = "" if args.rate_multiplier == 1 else f"_x{args.rate_multiplier:g}"
    (HERE / f"replay_result{suffix}.json").write_text(json.dumps(result, indent=2, default=str))
    md = report_md(result, runs, records, rates, meta, args)
    (HERE / f"report{suffix}.md").write_text(md, encoding="utf-8")
    print(md if args.verbose else f"wrote cost/report{suffix}.md, cost/usage{'' if not suffix else suffix}.csv, cost/replay_result{suffix}.json")
    print(f"API spend cold ${per_run['cold']['api_usd']:.6f} | warm ${per_run['warm']['api_usd']:.6f} | "
          f"wall cold {runs['cold']['wall_s']:.1f}s warm {runs['warm']['wall_s']:.1f}s | rate multiplier {args.rate_multiplier}")
    return result


def report_md(res, runs, records, rates, meta, args):
    cold, warm = res["per_run"]["cold"], res["per_run"]["warm"]
    rc, rw = runs["cold"], runs["warm"]
    st = Counter(r["status"] for r in records if r["run"] == "cold")
    L = ["# 100-review cost and runtime calculator", "",
         f"Generated {res['generated_at']} by offline replay (`python -m cost.calculator replay`). No API key or model call is "
         f"used. Rate multiplier: **{res['rate_multiplier']}**. Rates: `{Path(res['rates_file']).name}`.", "",
         "## Measured pilot (real calls on `cost_100.csv`, unchanged)", "",
         f"- Input: `cost_100.csv`, sha256 `{rc['input_sha256']}` (manifest `c884ac3b...dd0e`: "
         f"{'match' if rc['input_sha256'].startswith('c884ac3b') else 'MISMATCH'}); {rc['ids']} IDs; {rc['unique_texts']} unique texts.",
         f"- Cold run `{rc['run_id']}` started {rc['started_at']} with an **empty result cache** and **1 worker**; "
         f"warm run `{rw['run_id']}` reused the saved cache.",
         f"- Cold statuses: {dict(st)}. Warm result-cache hits: {rw['cache_hits']} of {rw['ids']}; "
         f"new enrichment calls in warm run: **{warm['stages'].get('enrich', {}).get('attempts', 0)}**; "
         f"downstream calls in warm run: {sum(v.get('attempts', 0) for k, v in warm['stages'].items() if k != 'enrich')}.", "",
         "| Run | Wall-clock s | API spend USD | Local compute USD (est.) | Cost / 1,000 input rows | Cost / completed record | Throughput rows/min |",
         "|---|---|---|---|---|---|---|"]
    for name, r, run in (("cold", cold, rc), ("warm", warm, rw)):
        done = run["completed"]
        L.append(f"| {name} | {run['wall_s']:.2f} | {r['api_usd']:.6f} | {r['local_usd']:.6f} | {r['api_usd'] / run['ids'] * 1000:.6f} | "
                 f"{(r['api_usd'] / done) if done else 0:.8f} | {run['ids'] / (run['wall_s'] / 60):.1f} |")
    L += ["", "### By stage (cold run)", "",
          "| Stage | Provider | Model | Effort / thinking | Prompt+schema | Batch size | Workers | Requests ok | Failed attempts | "
          "Retries | Reviews sent | Uncached in | Cache write | Cache read | Output | USD | Stage wall s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for role in ("enrich", "verify", "group", "memo"):
        s = cold["stages"].get(role)
        cfg = rc["stage_config"].get(role, {})
        if not s:
            continue
        L.append(f"| {role} | anthropic | `{cfg.get('model')}` | {cfg.get('effort')} / {cfg.get('thinking')} | {cfg.get('label_config', '').split('+', 1)[-1]} | "
                 f"{cfg.get('batch_size')} | 1 | {s['succeeded']} | {s['failed']} | {s['retry_attempts']} | {s['reviews_sent']} | "
                 f"{s['uncached_input_tokens']:,} | {s['cache_write_tokens']:,} | {s['cache_read_tokens']:,} | {s['output_tokens']:,} | "
                 f"{s['cost_usd']:.6f} | {rc['stage_wall_s'].get(role, 0):.2f} |")
    L.append(f"| ingest+materialize+rank (code) | local | - | - | - | - | 1 | - | - | - | - | - | - | - | - | 0 API | "
             f"{sum(rc['stage_wall_s'].get(s, 0) for s in ('ingest', 'materialize', 'rank')):.2f} |")
    L += ["", f"Summed call durations (cold): {sum(s['summed_call_seconds'] for s in cold['stages'].values()):.2f}s vs wall clock "
          f"{rc['wall_s']:.2f}s (one worker, so they are close; with overlap they would not be).",
          f"Verification sample declared: {rc['verify_declared']} reviews. Fallback quota: {rc['fallback_quota']}.", "",
          "### Rates used (editable `cost/rates.csv`, standard tier, per million tokens)", "",
          "| Model | Item | USD / M tokens | Source | Checked |", "|---|---|---|---|---|"]
    for (model, item), row in sorted(meta.items()):
        if model.startswith("fake"):
            continue
        L.append(f"| {model} | {item} | {float(row['usd_per_million']) * res['rate_multiplier']:.4f} | {row['source_url']} | {row['checked_date']} |")
    L += ["", "Formula: `item_cost = billed_units x (usd_per_million / 1,000,000)`; items are mutually exclusive "
          "(uncached input, cache write, cache read, output). Thinking is disabled, so no reasoning tokens are billed separately. "
          "Per-call items are in `usage.csv`, joined to `pilot_calls.jsonl` by `request_id`.", "",
          "## Full-run projection", "",
          f"Measured enrichment unit cost: ${res['enrich_unit']['cost_per_text']:.8f} per distinct text "
          f"({res['enrich_unit']['texts_first_pass']} texts, {res['enrich_unit']['first_pass_requests']} first-pass requests). "
          f"Tokens/text: " + ", ".join(f"{k.replace('_tokens', '')} {v:.1f}" for k, v in res['enrich_unit']['tokens_per_text'].items()) + ".",
          f"Measured retry rate {res['unit_assumptions']['retry_rate_measured']:.3f} (share of texts re-sent once; already inside the "
          f"measured unit cost, so the base case adds nothing extra and the conservative case adds the difference); failed-attempt rate "
          f"{res['unit_assumptions']['failed_attempt_rate']:.3f}; fallback rate {res['unit_assumptions']['fallback_rate_measured']:.4f}; "
          f"fallback cost per text (estimate) ${res['unit_assumptions']['fallback_cost_per_text_estimate']:.5f}; fixed group+memo "
          f"${res['unit_assumptions']['fixed_overhead_usd']:.4f} added once.", "",
          f"Controls: budget **${res['assumptions']['budget_usd']}**, output cap {res['assumptions']['output_token_cap_per_enrich_request']} "
          f"tokens/request, max workers {res['assumptions']['max_workers']}, {res['assumptions']['requests_per_minute_limit']} requests/min, "
          f"fallback max fraction {res['assumptions']['fallback_max_fraction']}.", "",
          "| Scenario | Texts | Case | Retry | Enrich USD | Verify (n / USD) | Fixed USD | **API total USD** | Local USD est. | Hours | Limit | Budget |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in res["projections"]:
        for case in ("base", "conservative"):
            c = p[case]
            L.append(f"| {p['scenario']} | {p['texts_to_classify']:,} | {case} | {c['retry_rate']:.3f} | {c['enrich_usd']:.2f} | "
                     f"{c['verify_reviews']:,} / {c['verify_usd']:.2f} | {c['fixed_group_memo_usd']:.3f} | **{c['api_total_usd']:.2f}** | "
                     f"{c['local_compute_usd_estimate']:.3f} | {c['elapsed_hours']:.2f} | {c['binding_limit']} | "
                     f"{'**OVER BUDGET**' if c['over_budget'] else 'ok'} |")
    L += ["", "Every scenario accounts for all 660,622 rows (13 empty texts quarantined). The no-reuse row classifies every one of "
          "660,609 nonempty rows separately; the reuse rows send each distinct text once (484,189 for the full corpus).", ""]
    if res["refreshes"]:
        L += ["## Refreshed measurements (500-review checkpoint and the 100k-scope run)", "",
              "| Checkpoint | First-pass texts | Requests | Retry/split requests | Fallback | Failed attempts | USD | USD / text | Output tok / text |",
              "|---|---|---|---|---|---|---|---|---|"]
        for label, m in res["refreshes"].items():
            if m:
                L.append(f"| {label} | {m['texts_first_pass']:,} | {m['first_pass_requests']:,} | {m['retry_or_split_requests']} | "
                         f"{m['fallback_requests']} | {m['failed_attempts']} | {m['cost_usd']:.4f} | {m['cost_per_text']:.8f} | "
                         f"{m['tokens_per_text']['output_tokens']:.1f} |")
        L.append("")
    L += ["## Notes and unknowns", "",
          "- API spend is computed from provider-reported usage; it has not been reconciled against the Anthropic Console invoice "
          "(delayed billing) - compare `api_usd` with the Console usage page for the pilot date.",
          "- Local compute is a rough labelled assumption; dashboard hosting uses free tiers and is outside API spend.",
          "- Batch API pricing (50% off) is not used; it would trade turnaround time for price and is shown only in `rates.csv`.",
          "- Projections are estimates from a 100-review sample; rare failure modes and sustained rate limits may differ.", ""]
    return "\n".join(L)


def pilot(args):
    if not args.execute:
        print("Refusing to make paid calls without --execute. Offline replay: python -m cost.calculator replay")
        return
    from pipeline.__main__ import load_env
    from pipeline.common import file_sha, read_jsonl as rj
    from pipeline.config import ENRICH, GROUP, MEMO, VERIFY, Limits
    from pipeline.runner import run
    load_env()
    state = HERE / "state"
    if state.exists():
        # keep evidence of earlier (failed/aborted) pilot attempts before emptying the result cache
        try:
            from pipeline.store import Store as _S
            old = _S(state).calls()
            if old:
                arch = HERE / "pilot_attempts_archive"
                arch.mkdir(exist_ok=True)
                tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                with open(arch / f"calls_before_{tag}.jsonl", "w", encoding="utf-8") as f:
                    for c in old:
                        f.write(json.dumps(c, ensure_ascii=False) + "\n")
                print(f"archived {len(old)} calls from a previous pilot attempt to {arch.name}/")
        except Exception as e:
            print("could not archive previous attempt:", e)
        shutil.rmtree(state)  # empty result cache for the cold experiment
    inp = ROOT / "data" / "cost_100.csv"
    lim = Limits(budget_usd=args.budget_usd, workers=1, verify_fraction=0.2, verify_min=20, verify_max=20,
                 requests_per_minute=args.rpm)
    runs, all_calls, pilot_records = {}, [], []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name in ("cold", "warm"):
        rid = f"pilot-{name}-{stamp}"
        t0 = time.monotonic()
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        res = run(str(inp), state, "all", args.provider, lim, None, run_id=rid)
        wall = time.monotonic() - t0
        if res["stop_reason"] != "finished":
            print(f"pilot {name} stopped: {res['stop_reason']}\nNot writing pilot files; fix the error and rerun "
                  f"(the attempt's calls are kept in cost/state and archived on the next run).")
            return
        recs = list(rj(state / "outputs" / "records.jsonl.gz"))
        from pipeline.store import Store
        st = Store(state)
        calls = [c for c in st.calls() if c["run_id"] == rid]
        enrich_calls = [c for c in calls if c["role"] == "enrich"]
        sent = {i for c in enrich_calls if c["outcome"] == "succeeded" for i in c["review_ids"]}
        for r in recs:
            pilot_records.append({**r, "run": name, "run_id": rid, "result_cache_hit": r["review_id"] not in sent and r["status"] == "completed"})
        all_calls += calls
        runs[name] = {"run_id": rid, "started_at": started, "wall_s": round(wall, 3), "stage_wall_s": res["timings"],
                      "input_sha256": file_sha(inp), "ids": len(recs), "unique_texts": len({r['review_id'] for r in recs}),
                      "completed": sum(r["status"] == "completed" for r in recs),
                      "failed_or_quarantined": sum(r["status"] != "completed" for r in recs),
                      "cache_hits": sum(1 for r in recs if r["review_id"] not in sent and r["status"] == "completed"),
                      "verify_declared": 20, "fallback_quota": "max(1, 0.5% of texts)",
                      "stage_config": {c.role: {"model": c.model, "effort": c.effort, "thinking": c.thinking,
                                                "label_config": c.label_config, "batch_size": c.batch_size}
                                       for c in (ENRICH, VERIFY, GROUP, MEMO)}}
        print(f"pilot {name}: wall {wall:.1f}s, calls {len(calls)}, stop {res['stop_reason']}")
    ing = Store(state).get("ingest")
    runs["cold"]["unique_texts"] = ing["distinct_nonempty_texts"]
    runs["warm"]["unique_texts"] = ing["distinct_nonempty_texts"]
    with open(HERE / "pilot_calls.jsonl", "w", encoding="utf-8") as f:
        for c in all_calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(HERE / "pilot_records.jsonl", "w", encoding="utf-8") as f:
        for r in pilot_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (HERE / "pilot_runs.json").write_text(json.dumps(runs, indent=2))
    for name in ("memo.md", "ranking.csv", "issues.json"):
        p = state / "outputs" / name
        if p.exists():
            shutil.copyfile(p, HERE / f"pilot_{name}")
    args.rate_multiplier = 1.0
    replay(args)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    for name in ("replay", "pilot"):
        s = sub.add_parser(name)
        s.add_argument("--rates", default=str(HERE / "rates.csv"))
        s.add_argument("--assumptions", default=str(HERE / "assumptions.json"))
        s.add_argument("--rate-multiplier", type=float, default=1.0)
        s.add_argument("--refresh", action="append", help="label=path/to/run_log.jsonl")
        s.add_argument("--verbose", action="store_true")
        if name == "pilot":
            s.add_argument("--execute", action="store_true", help="required: makes real paid API calls")
            s.add_argument("--budget-usd", type=float, default=2.0)
            s.add_argument("--rpm", type=int, default=50)
            s.add_argument("--provider", default="anthropic", choices=["anthropic", "fake"], help="fake = offline plumbing test only")
    a = p.parse_args()
    if a.cmd in (None, "replay"):
        if a.cmd is None:
            a = p.parse_args(["replay"])
        replay(a)
    else:
        pilot(a)


if __name__ == "__main__":
    main()
