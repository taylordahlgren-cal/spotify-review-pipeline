"""CLI. Paid model calls happen only in `run` with --provider anthropic (the default for `run`).

  python -m pipeline run --input data/spotify_reviews_18months.csv --state runs/final --scope sample:100000 --workers 8 --budget-usd 25
  python -m pipeline status --state runs/final
  python -m pipeline rank   --state runs/final            # regenerate ranking from saved outputs, no model calls
  python -m pipeline export --state runs/final --input data/spotify_reviews_18months.csv --out grading
  python -m pipeline planted --state runs/final --out evals  # planted-error test from saved verifier labels, no calls
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import ROOT, Limits


def load_env():
    path = ROOT / ".env"
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
    except ImportError:
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    p = argparse.ArgumentParser(prog="pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run stages (ingest, enrich, verify, materialize, group, rank, memo)")
    r.add_argument("--input", required=True)
    r.add_argument("--state", required=True)
    r.add_argument("--scope", default="all", help="all | sample:N | ids:path.csv")
    r.add_argument("--provider", default="anthropic", choices=["anthropic", "fake"])
    r.add_argument("--stages", default="ingest,enrich,verify,materialize,group,rank,memo")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--rpm", type=int, default=50, help="shared requests-per-minute limit")
    r.add_argument("--budget-usd", type=float, default=40.0, help="cumulative spend cap for this state dir")
    r.add_argument("--stop-after-texts", type=int, default=None, help="deliberately stop after N texts (resume demo)")
    r.add_argument("--verify-fraction", type=float, default=0.02)
    r.add_argument("--verify-max", type=int, default=2000)
    r.add_argument("--verify-min", type=int, default=20)
    r.add_argument("--fallback-max-fraction", type=float, default=0.005)
    r.add_argument("--inject-failure-rate", type=float, default=0.0, help="synthetic transient failures (control demo only)")
    for name in ("status", "rank", "planted"):
        s = sub.add_parser(name)
        s.add_argument("--state", required=True)
        if name == "planted":
            s.add_argument("--out", default="evals")
    e = sub.add_parser("export")
    e.add_argument("--state", required=True)
    e.add_argument("--input", required=True)
    e.add_argument("--out", default="grading")
    a = p.parse_args()

    if a.cmd == "run":
        load_env()
        from .runner import run
        lim = Limits(budget_usd=a.budget_usd, workers=a.workers, requests_per_minute=a.rpm,
                     stop_after_texts=a.stop_after_texts, verify_fraction=a.verify_fraction, verify_max=a.verify_max,
                     verify_min=a.verify_min, fallback_max_fraction=a.fallback_max_fraction,
                     inject_failure_rate=a.inject_failure_rate)
        res = run(a.input, a.state, a.scope, a.provider, lim, [s.strip() for s in a.stages.split(",") if s.strip()])
        print(json.dumps({k: res[k] for k in ("phase", "stop_reason", "timings", "ledger", "wall_s")}, indent=2))
    elif a.cmd == "status":
        from .runner import status
        s = status(a.state)
        print(json.dumps({k: s[k] for k in ("run_id", "text_results", "pending_texts", "texts_with_transport_failures",
                                            "total_cost_usd_from_usage")}, indent=2))
        for ss in s["sessions"]:
            print(f"  session {ss['n']} {ss['phase']:8s} {ss['stop_reason']}  ids {ss['completed_ids_start']} -> {ss['completed_ids_end']}")
    elif a.cmd == "rank":
        from .runner import offline_rank
        offline_rank(a.state)
    elif a.cmd == "planted":
        from .store import Store
        from .verify import planted_error_test
        print(json.dumps({k: v for k, v in planted_error_test(Store(a.state), Path(a.out)).items() if k != "cases"}, indent=2))
    elif a.cmd == "export":
        from .runner import export_grading
        export_grading(a.state, a.input, a.out)


if __name__ == "__main__":
    main()
