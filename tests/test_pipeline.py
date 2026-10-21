"""Offline tests (fake provider, no API key, no network). Run: python -m pytest -q"""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from pipeline import llm
from pipeline.analysis import rank
from pipeline.common import FIELDS, read_jsonl, row_sha
from pipeline.config import Limits, load_rates
from pipeline.enrich import cache_key, pending_texts, run_enrich
from pipeline.ingest import ingest
from pipeline.llm import BudgetExceeded, LLMClient, RateLimiter, SpendLedger
from pipeline.runner import export_grading, run
from pipeline.schema import resolve_quote, validate_enrich_item
from pipeline.store import Store

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
spec = importlib.util.spec_from_file_location("cs", ROOT / "check_submission.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


@pytest.fixture(autouse=True)
def reset_faults():
    llm.FAKE_FAULTS.clear()
    yield
    llm.FAKE_FAULTS.clear()


def fast(**kw):
    return Limits(requests_per_minute=100000, budget_usd=1.0, **kw)


def client(store, limits, rates=None, phase="initial"):
    return LLMClient("fake", SpendLedger(limits.budget_usd), RateLimiter(limits.requests_per_minute),
                     rates or load_rates(), limits, "test", "s-test", phase)


def test_row_sha_matches_checker():
    with open(DATA / "cost_100.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            assert row_sha({k: row[k] for k in FIELDS}) == cs.row_sha(row)


def test_quote_resolution_never_invents_text():
    text = "The app  crashes\nevery time I open it."
    assert resolve_quote("*", text)[0] == text
    assert resolve_quote("crashes every time", text)[0] == "crashes\nevery time"  # whitespace mapped back to source chars
    assert resolve_quote("it crashes constantly", text) == (text.strip(), "quote_replaced_with_full_text")  # short review
    long_text = "x" * 400
    assert resolve_quote("not there", long_text)[0] is None
    rec, why = validate_enrich_item({"topic": "playback", "subtopic": "crashes_or_wont_open", "intent": "complaint",
                                     "sentiment": -0.8, "severity": 4, "entities": [], "quote": "not in text",
                                     "needs_review": False, "reason": ""}, long_text)
    assert rec is None and why == "quote_not_in_source"


def test_invalid_label_values_rejected():
    base = {"topic": "playback", "subtopic": "other", "intent": "complaint", "sentiment": -0.5, "severity": 3,
            "entities": [], "quote": "*", "needs_review": False, "reason": ""}
    assert validate_enrich_item(base, "x")[0]
    for k, v in [("topic", "ads"), ("intent", "angry"), ("severity", 7), ("severity", "3"), ("sentiment", 1.5)]:
        assert validate_enrich_item({**base, k: v}, "x")[0] is None


def test_retry_once_then_quarantine_and_transient_backoff(tmp_path):
    store = Store(tmp_path / "s")
    ingest(store, DATA / "cost_100.csv", "all", log=lambda *a: None)
    lim = fast(fallback_max_fraction=0.0)
    # 2 transient errors, a dropped key on the first response, and bad quotes on the first two responses
    llm.FAKE_FAULTS.update({"transient": 2, "drop_key": 1, "bad_quote": 3})
    c = client(store, lim)
    stats = run_enrich(store, c, lim, "s-test", log=lambda *a: None)
    calls = store.calls()
    assert sum(x["outcome"] == "failed" for x in calls) == 2          # transient failures logged as failed attempts
    assert any(x.get("validation_attempt") == 2 for x in calls)        # invalid output retried once
    assert all(len(x["review_ids"]) <= 50 for x in calls if x["role"] == "enrich")
    st = dict(store.db.execute("SELECT status, COUNT(*) FROM results GROUP BY status").fetchall())
    assert st.get("completed", 0) + st.get("quarantined", 0) == 100
    assert stats["remaining_pending"] == 0


def test_budget_cap_stops_before_dispatch(tmp_path):
    store = Store(tmp_path / "s")
    ingest(store, DATA / "cost_100.csv", "all", log=lambda *a: None)
    rates = load_rates()
    rates["fake-keyword-v1"] = dict(rates["claude-haiku-5-5"])
    lim = Limits(requests_per_minute=100000, budget_usd=0.002)  # less than one worst-case enrichment reservation
    c = client(store, lim, rates)
    stats = run_enrich(store, c, lim, "s-test", log=lambda *a: None)
    assert stats["stop_reason"].startswith("budget")
    assert c.ledger.spent <= 0.002
    assert len(pending_texts(store)) > 0  # unfinished work stays pending, not dropped


def test_fatal_error_stops_run(tmp_path):
    llm.FAKE_FAULTS["fatal"] = True
    res = run(DATA / "cost_100.csv", tmp_path / "s", "all", "fake", fast(), log=lambda *a: None)
    assert res["stop_reason"].startswith("fatal_api_error")


def test_resume_no_relabel_and_checker_passes(tmp_path):
    state = tmp_path / "s"
    r1 = run(DATA / "checkpoint_500.csv", state, "all", "fake", fast(stop_after_texts=200), log=lambda *a: None)
    assert r1["phase"] == "initial" and r1["stop_reason"].startswith("stop_after")
    r2 = run(DATA / "checkpoint_500.csv", state, "all", "fake", fast(), log=lambda *a: None)
    assert r2["phase"] == "resume" and r2["stop_reason"] == "finished"
    store = Store(state)
    before = set(json.loads((state / "checkpoints" / "session-02-start.json").read_text())["completed_ids"])
    resumed = [c for c in store.calls() if c["role"] == "enrich" and c["phase"] == "resume"]
    assert resumed and not before.intersection(i for c in resumed for i in c["review_ids"])
    out = tmp_path / "grading"
    export_grading(state, DATA / "checkpoint_500.csv", out, log=lambda *a: None)
    ref = cs.reference(DATA / "checkpoint_500.csv", DATA / "checkpoint_500.csv")
    result = cs.audit(out, ref)
    assert result["status"] == "pass", result["issue_counts"]
    # a third run under unchanged settings sends zero enrichment calls
    n_before = len(store.calls())
    run(DATA / "checkpoint_500.csv", state, "all", "fake", fast(), log=lambda *a: None)
    assert len(Store(state).calls()) == n_before


def test_rank_is_deterministic_and_matches_checker(tmp_path):
    state = tmp_path / "s"
    run(DATA / "checkpoint_500.csv", state, "all", "fake", fast(), log=lambda *a: None)
    o = state / "outputs"
    first = (o / "ranking.csv").read_text()
    rank(o / "records.jsonl.gz", o / "membership.csv", tmp_path / "rerank", log=lambda *a: None)
    assert (tmp_path / "rerank" / "ranking.csv").read_text() == first
    out = tmp_path / "g"
    export_grading(state, DATA / "checkpoint_500.csv", out, log=lambda *a: None)
    calc = cs.audit(out, cs.reference(DATA / "checkpoint_500.csv", DATA / "checkpoint_500.csv"))["calculated_ranking"]
    with open(o / "ranking.csv") as f:
        mine = list(csv.DictReader(f))
    assert [r["issue_id"] for r in mine] == [r["issue_id"] for r in calc]
    assert [r["mean_severity"] for r in mine] == [r["mean_severity"] for r in calc]


def test_memo_checker_rejects_invented_numbers(tmp_path):
    from pipeline.memo import build_pack, check_memo
    state = tmp_path / "s"
    run(DATA / "checkpoint_500.csv", state, "all", "fake", fast(), log=lambda *a: None)
    pack, claims = build_pack(state / "outputs")
    top = pack["ranking"][0]
    good = {"title": "t", "recommendation": f"Fix {top['issue_id']}: {top['complaint_count']} complaints [{top['claims']['complaint_count']}].",
            "supporting_evidence": [], "alternatives": [], "dashboard_recommendations": [], "limitations": []}
    assert check_memo(good, pack)[0] == []
    bad = dict(good, recommendation="This will cut churn by 37.5% and save $4,000,000 [C99].")
    probs = check_memo(bad, pack)[0]
    assert any("37.5" in p for p in probs) and any("C99" in p for p in probs)


def test_rate_doubling_doubles_api_cost():
    from cost.calculator import price_calls, load_rates as lr
    calls = [{"run_id": "r", "request_id": "a", "role": "enrich", "model": "claude-haiku-5-5", "outcome": "succeeded",
              "uncached_input_tokens": 1000, "cache_write_tokens": 2000, "cache_read_tokens": 3000, "output_tokens": 4000}]
    r1, _ = lr(ROOT / "cost" / "rates.csv", 1.0)
    r2, _ = lr(ROOT / "cost" / "rates.csv", 2.0)
    c1 = sum(x["item_cost_usd"] for x in price_calls(calls, r1))
    c2 = sum(x["item_cost_usd"] for x in price_calls(calls, r2))
    assert c1 == pytest.approx(1000 * 0.1e-6 + 2000 * 0.125e-6 + 3000 * 0.01e-6 + 4000 * 0.5e-6)
    assert c2 == pytest.approx(2 * c1)
