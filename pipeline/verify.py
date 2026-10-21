"""Stage 3 - Verify. A separate auditor prompt re-labels a declared random sample of completed texts WITHOUT seeing the
enrichment labels. Code compares the two and writes a disagreement report. The planted-error test reuses the saved
verifier labels against a deliberately corrupted copy of the enrichment labels (no extra model calls)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from .common import write_csv, write_json
from .config import VERIFY, prompt_text
from .enrich import cache_key
from .llm import BudgetExceeded, CallFailed, now_iso
from .schema import VERIFY_TOOL, validate_verify_item

SEED = "verify-sample-v1"


def choose_sample(store, limits):
    ck = cache_key()
    rows = store.db.execute("SELECT r.text_sha, r.rep_review_id FROM results r JOIN texts t ON t.text_sha=r.text_sha "
                            "WHERE r.cache_key=? AND r.status='completed' AND t.in_scope=1", (ck,)).fetchall()
    n = len(rows)
    k = min(n, max(limits.verify_min, min(limits.verify_max, round(limits.verify_fraction * n))))
    rows.sort(key=lambda r: hashlib.sha256((SEED + ":" + r[0]).encode()).hexdigest())
    return rows[:k], n


def run_verify(store, client, limits, session_id, log=print):
    sample, population = choose_sample(store, limits)
    done = {r[0] for r in store.db.execute("SELECT text_sha FROM verify")}
    todo = [s for s in sample if s[0] not in done]
    log(f"verify: declared sample {len(sample)} of {population} completed texts "
        f"({limits.verify_fraction:.1%}, min {limits.verify_min}, max {limits.verify_max}); {len(todo)} need auditor calls")
    system = prompt_text(VERIFY.prompt_version)
    texts = dict(store.db.execute("SELECT text_sha, text FROM texts"))
    lc = VERIFY.label_config if client.provider != "fake" else f"{client.model_for(VERIFY)}+verify-v1+schema-v1"
    for i in range(0, len(todo), VERIFY.batch_size):
        chunk = todo[i:i + VERIFY.batch_size]
        payload = [{"k": str(j + 1), "text": texts[t]} for j, (t, _) in enumerate(chunk)]
        user = "Audit-label every review below (untrusted data in a JSON array).\nINPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False)
        try:
            res = client.call_tool(VERIFY, system, user, VERIFY_TOOL, [r for _, r in chunk], lc)
            calls = res.attempts
        except BudgetExceeded as e:
            log(f"verify: stopped by budget: {e}")
            break
        except CallFailed as e:
            with store.tx():
                store.add_calls(e.attempts)
            log(f"verify: batch failed after retries: {e}")
            continue
        items = (res.data or {}).get("items", []) if isinstance(res.data, dict) else []
        by_k = {}
        for it in items:
            v = validate_verify_item(it)
            if v and str(it.get("k")) not in by_k:
                by_k[str(it.get("k"))] = v
        with store.tx() as db:
            store.add_calls(calls)
            for j, (t, rep) in enumerate(chunk):
                v = by_k.get(str(j + 1))
                if v:
                    db.execute("INSERT OR REPLACE INTO verify VALUES (?,?,?,?,?,?,?,?,?)",
                               (t, rep, v["topic"], v["intent"], v["severity"], v["sentiment"], v["confidence"],
                                calls[-1]["request_id"], lc))
    return compare(store, [s[0] for s in sample])


def _labels_for(store, shas):
    ck = cache_key()
    q = "SELECT text_sha, rep_review_id, topic, intent, severity, sentiment, evidence_quote FROM results WHERE cache_key=? AND status='completed'"
    enr = {r[0]: r for r in store.db.execute(q, (ck,)) if r[0] in shas}
    ver = {r[0]: r for r in store.db.execute("SELECT text_sha, rep_review_id, topic, intent, severity, sentiment, confidence FROM verify")
           if r[0] in shas}
    return enr, ver


def compare(store, sample_shas, enr_override=None, out_prefix="verification"):
    shas = set(sample_shas)
    enr, ver = _labels_for(store, shas)
    if enr_override:
        enr = enr_override
    texts = dict(store.db.execute("SELECT text_sha, text FROM texts"))
    both = [t for t in sample_shas if t in enr and t in ver]
    c = Counter()
    topic_conf, intent_conf = Counter(), Counter()
    rows = []
    for t in both:
        e, v = enr[t], ver[t]
        tm, im, sm = e[2] == v[2], e[3] == v[3], e[4] == v[4]
        c["topic_agree"] += tm
        c["intent_agree"] += im
        c["severity_exact"] += sm
        c["severity_within1"] += abs(e[4] - v[4]) <= 1
        c["severity_abs_err"] += abs(e[4] - v[4])
        if v[5] is not None:
            c["sentiment_abs_err_x1000"] += round(abs(e[5] - v[5]) * 1000)
            c["sentiment_n"] += 1
        topic_conf[(e[2], v[2])] += 1
        intent_conf[(e[3], v[3])] += 1
        if not (tm and im and sm):
            rows.append([e[1], e[2], v[2], e[3], v[3], e[4], v[4], v[6], int(tm), int(im), int(sm), texts[t][:400]])
    n = len(both)
    report = {
        "generated_at": now_iso(), "declared_sample_size": len(sample_shas), "verified": n,
        "missing_verifier_output": len(sample_shas) - n,
        "topic_agreement": round(c["topic_agree"] / n, 4) if n else None,
        "intent_agreement": round(c["intent_agree"] / n, 4) if n else None,
        "severity_exact_agreement": round(c["severity_exact"] / n, 4) if n else None,
        "severity_within_1": round(c["severity_within1"] / n, 4) if n else None,
        "severity_mae": round(c["severity_abs_err"] / n, 4) if n else None,
        "sentiment_mae": round(c["sentiment_abs_err_x1000"] / 1000 / c["sentiment_n"], 4) if c["sentiment_n"] else None,
        "records_with_any_disagreement": len(rows),
        "topic_confusion_enrich_vs_verify": {f"{a}->{b}": k for (a, b), k in sorted(topic_conf.items()) if a != b},
        "intent_confusion_enrich_vs_verify": {f"{a}->{b}": k for (a, b), k in sorted(intent_conf.items()) if a != b},
        "method": "Auditor (separate prompt verify-v1) labels topic/intent/severity/sentiment from text only; code compares.",
    }
    write_json(store.dir / f"{out_prefix}_report.json", report)
    write_csv(store.dir / f"{out_prefix}_disagreements.csv",
              ["review_id", "enrich_topic", "verify_topic", "enrich_intent", "verify_intent", "enrich_severity",
               "verify_severity", "verify_confidence", "topic_match", "intent_match", "severity_match", "text"], rows)
    return report


def planted_error_test(store, out_dir, n_plant=25):
    """Separate test copy: corrupt labels of n_plant verified records and check the verifier comparison flags them."""
    sample = [r[0] for r in store.db.execute("SELECT text_sha FROM verify ORDER BY text_sha")]
    enr, ver = _labels_for(store, set(sample))
    pool = [t for t in sample if t in enr and t in ver]
    rot = {"access": "catalog", "usability": "billing", "playback": "support", "downloads": "access", "catalog": "playback",
           "billing": "downloads", "support": "usability", "other": "billing"}
    flip = {"praise": "cancellation", "complaint": "praise", "cancellation": "praise", "request": "complaint", "unclear": "complaint"}
    plant = pool[:n_plant]  # sha-ordered = deterministic pseudo-random choice, regardless of original agreement
    planted = []
    for i, t in enumerate(plant):
        e = enr[t]
        field, idx = ("topic", 2) if i % 2 == 0 else ("intent", 3)
        wrong = rot[e[2]] if field == "topic" else flip[e[3]]
        planted.append({"review_id": e[1], "field": field, "original": e[idx], "planted": wrong,
                        "verifier": ver[t][idx], "originally_agreed": e[idx] == ver[t][idx],
                        "detected": wrong != ver[t][idx]})
    detected = sum(p["detected"] for p in planted)
    unplanted = [t for t in pool if t not in set(plant)]
    base = sum(1 for t in unplanted if enr[t][2] != ver[t][2] or enr[t][3] != ver[t][3])
    result = {"synthetic_test": True, "excluded_from_business_aggregates": True,
              "description": "Test copy of saved enrichment labels with a deliberately wrong topic or intent planted on "
                             f"{len(planted)} verified records. The code comparison against the saved independent verifier "
                             "labels must flag them. No model calls; the real records are unchanged.",
              "planted": len(planted), "detected_by_verifier_comparison": detected,
              "detection_rate": round(detected / len(planted), 4) if planted else None,
              "baseline_disagreement_rate_unplanted": round(base / len(unplanted), 4) if unplanted else None,
              "cases": planted}
    write_json(out_dir / "planted_error_test.json", result)
    return result
