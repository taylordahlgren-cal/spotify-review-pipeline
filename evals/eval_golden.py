"""Golden-50 evaluation (no model calls). Compares human labels with saved pipeline predictions.

    python -m evals.eval_golden --labels evals/golden_50_labeled.csv --records runs/final/outputs/records.jsonl.gz

Human labels are read only here, after the run; they are never model inputs. Predictions come from the full run
(the golden texts are part of the classified corpus). Missing/quarantined predictions count as incorrect.
"""
import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
SENTIMENT_TOLERANCE = 0.3  # predeclared: |pred - human| <= 0.3 counts as sentiment agreement


def read_records(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return {r["review_id"]: r for r in (json.loads(l) for l in f if l.strip())}


def f1_table(pairs, labels):
    out = {}
    for lab in labels:
        tp = sum(h == lab and p == lab for h, p in pairs)
        sup = sum(h == lab for h, _ in pairs)
        pred = sum(p == lab for _, p in pairs)
        if sup or pred:
            out[lab] = {"support": sup, "predicted": pred, "precision": round(tp / pred, 3) if pred else None,
                        "recall": round(tp / sup, 3) if sup else None, "f1": round(2 * tp / (sup + pred), 3)}
    sup_labels = [v for v in out.values() if v["support"]]
    return out, round(sum(v["f1"] for v in sup_labels) / len(sup_labels), 3) if sup_labels else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(ROOT / "evals" / "golden_50_labeled.csv"))
    ap.add_argument("--records", required=True)
    ap.add_argument("--out", default=str(ROOT / "evals"))
    a = ap.parse_args()
    with open(a.labels, encoding="utf-8-sig", newline="") as f:
        gold = list(csv.DictReader(f))
    recs = read_records(a.records)
    cases, c = [], Counter()
    tp, ip, sp = [], [], []
    for g in gold:
        rid, text = g["review_id"], g["review_text"]
        p = recs.get(rid, {})
        valid = p.get("status") == "completed"
        hs, ps = int(g["severity"]), p.get("severity") if valid else None
        hsent = float(g["sentiment"]) if g["sentiment"].strip() else None  # blank = human left sentiment unlabelled
        psent = p.get("sentiment") if valid else None
        has_sent = hsent is not None
        topic_ok = valid and p["topic"] == g["topic"]
        intent_ok = valid and p["intent"] == g["intent"]
        sev_ok = valid and ps == hs
        sent_ok = valid and has_sent and abs(psent - hsent) <= SENTIMENT_TOLERANCE
        quote_in = valid and p["evidence_quote"] in text
        ents = p.get("entities", []) if valid else []
        unsupported_ents = [e for e in ents if e.lower() not in text.lower()]
        hn = g["needs_review"].strip().lower() == "true"
        ambiguous = bool(g.get("notes", "").strip()) or hn
        c["n"] += 1
        c["valid"] += valid
        c["topic"] += topic_ok
        c["intent"] += intent_ok
        c["severity_exact"] += sev_ok
        c["severity_within1"] += valid and abs(ps - hs) <= 1
        c["sev_abs"] += abs(ps - hs) if valid else 0
        c["sent_ok"] += sent_ok
        c["sent_n"] += has_sent
        c["sent_valid_n"] += valid and has_sent
        c["sent_abs_x1000"] += round(abs(psent - hsent) * 1000) if valid and has_sent else 0
        c["joint"] += topic_ok and intent_ok and sev_ok
        c["quote_substring"] += quote_in
        c["quote_full_text"] += valid and p["evidence_quote"].strip() == text.strip()
        c["unsupported_entities"] += len(unsupported_ents)
        c["ambiguous"] += ambiguous
        c["needs_tp"] += valid and hn and p["needs_review"]
        c["needs_pred"] += valid and p["needs_review"]
        c["needs_human"] += hn
        tp.append((g["topic"], p.get("topic", "<missing>") if valid else "<missing>"))
        ip.append((g["intent"], p.get("intent", "<missing>") if valid else "<missing>"))
        sp.append((str(hs), str(ps)))
        cases.append({"review_id": rid, "text": text, "human_topic": g["topic"], "pred_topic": p.get("topic"),
                      "human_intent": g["intent"], "pred_intent": p.get("intent"), "human_severity": hs, "pred_severity": ps,
                      "human_sentiment": hsent, "pred_sentiment": psent, "topic_ok": topic_ok, "intent_ok": intent_ok,
                      "severity_ok": sev_ok, "sentiment_ok": sent_ok, "quote": p.get("evidence_quote"),
                      "quote_is_substring": quote_in, "entities": ents, "unsupported_entities": unsupported_ents,
                      "human_needs_review": hn, "pred_needs_review": p.get("needs_review"), "ambiguous_or_noted": ambiguous,
                      "human_notes": g.get("notes", ""), "status": p.get("status", "missing")})
    n = c["n"]
    topic_f1, topic_macro = f1_table(tp, TOPICS)
    intent_f1, intent_macro = f1_table(ip, INTENTS)
    conf = Counter(tp)
    res = {"n": n, "valid_predictions": c["valid"],
           "topic_agreement": round(c["topic"] / n, 3), "intent_agreement": round(c["intent"] / n, 3),
           "severity_exact_agreement": round(c["severity_exact"] / n, 3), "severity_within_1": round(c["severity_within1"] / n, 3),
           "severity_mae_valid": round(c["sev_abs"] / max(1, c["valid"]), 3),
           "sentiment_agreement_tol_0.3": round(c["sent_ok"] / max(1, c["sent_n"]), 3), "sentiment_labelled_cases": c["sent_n"],
           "sentiment_mae_valid": round(c["sent_abs_x1000"] / 1000 / max(1, c["sent_valid_n"]), 3),
           "joint_topic_intent_severity": round(c["joint"] / n, 3),
           "quote_exact_substring_rate": round(c["quote_substring"] / n, 3), "quote_is_full_text": c["quote_full_text"],
           "unsupported_entities_total": c["unsupported_entities"], "ambiguous_cases": c["ambiguous"],
           "needs_review": {"human_true": c["needs_human"], "predicted_true": c["needs_pred"], "both_true": c["needs_tp"]},
           "topic_per_class": topic_f1, "topic_macro_f1": topic_macro, "intent_per_class": intent_f1, "intent_macro_f1": intent_macro,
           "topic_confusion_human_to_pred": {f"{h}->{p}": k for (h, p), k in sorted(conf.items())},
           "severity_confusion_human_to_pred": {f"{h}->{p}": k for (h, p), k in sorted(Counter(sp).items())},
           "sentiment_tolerance_predeclared": SENTIMENT_TOLERANCE,
           "note": "50 cases are a small diagnostic sample, not a population accuracy estimate. Golden labels were "
                   "not used in prompts, examples, thresholds or routing."}
    out = Path(a.out)
    (out / "golden_results.json").write_text(json.dumps(res, indent=2))
    with open(out / "golden_cases.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0].keys()))
        w.writeheader()
        for r in cases:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()})
    print(json.dumps({k: v for k, v in res.items() if not isinstance(v, dict)}, indent=2))


if __name__ == "__main__":
    main()
