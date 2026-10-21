"""Versioned model/prompt/schema configuration. Changing any of these changes label_config and invalidates the result cache."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
RATES_CSV = ROOT / "cost" / "rates.csv"

SCHEMA_VERSION = "schema-v1"

# Model allowlist: any other model ID is refused by the client.
MODEL_ALLOWLIST = {"claude-haiku-5-5", "claude-sonnet-5-5", "fake-keyword-v1"}


@dataclass(frozen=True)
class RoleConfig:
    role: str
    model: str
    prompt_version: str
    effort: str = "low"          # output_config.effort
    thinking: str = "disabled"   # thinking.type
    max_tokens: int = 4000
    batch_size: int = 1
    temperature: float | None = None  # not accepted by the current Messages API/SDK (anthropic 1.16)

    @property
    def settings_id(self) -> str:
        return f"{self.model}:effort={self.effort}:thinking={self.thinking}"

    @property
    def label_config(self) -> str:
        return f"{self.settings_id}+{self.prompt_version}+{SCHEMA_VERSION}"


ENRICH = RoleConfig("enrich", "claude-haiku-5-5", "enrich-v1", max_tokens=8000, batch_size=50)
# Fallback for records whose output stays invalid after one retry; capped by FALLBACK_MAX_FRACTION.
ENRICH_FALLBACK = RoleConfig("enrich", "claude-sonnet-5-5", "enrich-v1", max_tokens=1500, batch_size=1)
VERIFY = RoleConfig("verify", "claude-haiku-5-5", "verify-v1", max_tokens=6000, batch_size=50)
GROUP = RoleConfig("group", "claude-haiku-5-5", "group-v1", max_tokens=6000)
MEMO = RoleConfig("memo", "claude-sonnet-5-5", "memo-v2", max_tokens=6000)  # v2: explicit bracket-ID rule (after v1 wrote [C-none])

FAKE_MODEL = "fake-keyword-v1"


@dataclass
class Limits:
    budget_usd: float = 40.0            # hard spend cap for this invocation's ledger (spent + reserved)
    workers: int = 1
    requests_per_minute: int = 50
    max_attempts: int = 4               # transport attempts per request (429/5xx/timeouts) with backoff + jitter
    invalid_output_retries: int = 1     # contract: retry invalid output once
    fallback_max_fraction: float = 0.005  # max share of enriched texts that may use the stronger fallback model
    verify_fraction: float = 0.02       # declared random verification sample of completed distinct texts
    verify_max: int = 2000
    verify_min: int = 20
    request_timeout_s: float = 120.0
    stop_after_texts: int | None = None  # deliberate interruption for the resume demonstration
    inject_failure_rate: float = 0.0    # synthetic transient failures for control demos (labelled in logs)


def load_rates(path: Path = RATES_CSV) -> dict:
    """{model: {billing_item: usd_per_token}} for the standard (<=100k prompt) tier."""
    rates: dict = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("processing_tier", "standard") != "standard":
                continue
            rates.setdefault(row["model"], {})[row["billing_item"]] = float(row["usd_per_million"]) / 1_000_000
    return rates


def prompt_text(version: str) -> str:
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")
