"""Stage 1 - Prepare (code only, no model). Reads every row, preserves IDs/source values, profiles quality,
finds exact duplicate texts, selects the declared classification scope and builds the pending queue."""
from __future__ import annotations

import csv
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .common import FIELDS, csv_rows, file_sha, row_sha, sample_rank, text_sha, write_json


def parse_scope(spec: str):
    """'all' | 'sample:N' (first N nonempty rows in manifest sampling order) | 'ids:path.csv' (review_id column)."""
    if spec == "all":
        return ("all", None)
    if spec.startswith("sample:"):
        return ("sample", int(spec.split(":", 1)[1]))
    if spec.startswith("ids:"):
        path = spec.split(":", 1)[1]
        with open(path, encoding="utf-8-sig", newline="") as f:
            return ("ids", {r["review_id"] for r in csv.DictReader(f)})
    raise ValueError(f"bad scope {spec!r}")


def ingest(store, input_csv: str, scope_spec: str, log=print) -> dict:
    input_csv = str(input_csv)
    t0 = time.monotonic()
    sha = file_sha(input_csv)
    prev = store.get("ingest")
    if prev:
        if prev["input_sha256"] != sha or prev["scope"] != scope_spec:
            raise SystemExit(f"State dir already holds input {prev['input_sha256'][:12]} scope {prev['scope']}; "
                             f"use a new --state directory for a different input or scope.")
        log(f"ingest: already done for {Path(input_csv).name} ({prev['rows']} rows); reusing saved queue")
        return prev

    kind, arg = parse_scope(scope_spec)
    rows = []
    texts: dict[str, dict] = {}
    profile = Counter()
    ids = set()
    months, ratings = Counter(), Counter()
    empty_ids, dup_ids = [], []
    lengths = []
    first = last = None
    for idx, row in enumerate(csv_rows(input_csv)):
        rid = row["review_id"]
        profile["records"] += 1
        if rid in ids:
            profile["duplicate_review_ids"] += 1
            dup_ids.append(rid)
        ids.add(rid)
        text = row["review_text"]
        empty = not text.strip()
        profile["empty_review_text"] += empty
        profile["missing_app_version"] += not row["app_version"].strip()
        profile["missing_timestamp"] += not row["review_timestamp"].strip()
        profile["invalid_rating"] += row["review_rating"] not in {"1", "2", "3", "4", "5"}
        profile["multiline_text"] += ("\n" in text)
        profile["non_ascii_text"] += (not text.isascii())
        months[row["review_timestamp"][:7]] += 1
        ratings[row["review_rating"]] += 1
        ts = row["review_timestamp"]
        first = min(first, ts) if first else ts
        last = max(last, ts) if last else ts
        tsha = text_sha(text)
        if empty:
            empty_ids.append(rid)
        else:
            lengths.append(len(text))
        rows.append((rid, idx, row_sha(row), tsha, int(empty), row["review_rating"], row["review_likes"],
                     row["app_version"], ts, sample_rank(rid) if not empty else None))
        if not empty:
            t = texts.setdefault(tsha, {"text": text, "n": 0})
            t["n"] += 1

    # declared scope
    nonempty = [r for r in rows if not r[4]]
    if kind == "all":
        scope_ids = {r[0] for r in nonempty}
    elif kind == "sample":
        scope_ids = {r[0] for r in sorted(nonempty, key=lambda r: (r[9], r[0]))[:arg]}
    else:
        scope_ids = {r[0] for r in nonempty if r[0] in arg}
    # representative = in-scope row with lowest sample rank; queue priority follows that rank
    rep, prio, nscope = {}, {}, Counter()
    for r in nonempty:
        if r[0] in scope_ids:
            nscope[r[3]] += 1
            key = (r[9], r[0])
            if r[3] not in rep or key < prio[r[3]]:
                rep[r[3]], prio[r[3]] = r[0], key
    order = sorted(prio, key=lambda t: prio[t])
    priority = {t: i for i, t in enumerate(order)}

    with store.tx() as db:
        db.executemany("INSERT OR REPLACE INTO source VALUES (?,?,?,?,?,?,?,?,?,?)",
                       [(r[0], r[1], r[2], r[3], r[4], int(r[0] in scope_ids), r[5], r[6], r[7], r[8]) for r in rows])
        db.executemany("INSERT OR REPLACE INTO texts VALUES (?,?,?,?,?,?,?)",
                       [(t, v["text"], rep.get(t), priority.get(t), v["n"], nscope.get(t, 0), int(t in rep))
                        for t, v in texts.items()])

    lengths.sort()
    dup_text_rows = sum(v["n"] for v in texts.values() if v["n"] > 1)
    covered_rows = sum(texts[t]["n"] for t in rep)
    report = {
        "input_path": Path(input_csv).name, "input_sha256": sha, "input_bytes": Path(input_csv).stat().st_size,
        "rows": profile["records"], "scope": scope_spec,
        "profile": {k: profile[k] for k in ("records", "duplicate_review_ids", "empty_review_text", "missing_app_version",
                                             "missing_timestamp", "invalid_rating", "multiline_text", "non_ascii_text")},
        "nonempty_rows": len(nonempty), "distinct_nonempty_texts": len(texts),
        "rows_with_duplicated_text": dup_text_rows,
        "empty_text_review_ids": empty_ids, "duplicate_review_ids": dup_ids[:100],
        "text_length_chars": {"min": lengths[0] if lengths else 0, "median": lengths[len(lengths) // 2] if lengths else 0,
                              "p90": lengths[int(len(lengths) * .9)] if lengths else 0,
                              "p99": lengths[int(len(lengths) * .99)] if lengths else 0, "max": lengths[-1] if lengths else 0},
        "first_review": first, "last_review": last, "reviews_by_month": dict(sorted(months.items())),
        "reviews_by_rating": dict(sorted(ratings.items())),
        "scope_detail": {"declared": scope_spec, "in_scope_rows": len(scope_ids), "in_scope_distinct_texts": len(rep),
                         "rows_completable_by_exact_text_reuse": covered_rows,
                         "rows_outside_scope_without_matching_text": len(nonempty) - covered_rows,
                         "method": "sample:N = first N nonempty rows ordered by SHA-256(seed:review_id) as in manifest.json"},
        "quarantine_plan": {"empty_review_text": len(empty_ids)},
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wall_s": round(time.monotonic() - t0, 2),
    }
    write_json(store.dir / "ingestion_report.json", report)
    store.set("ingest", report)
    log(f"ingest: {report['rows']:,} rows, {len(texts):,} distinct nonempty texts, {len(empty_ids)} empty; "
        f"scope {scope_spec}: {len(scope_ids):,} rows / {len(rep):,} texts to classify "
        f"(covers {covered_rows:,} rows via exact-text reuse) in {report['wall_s']}s")
    return report
