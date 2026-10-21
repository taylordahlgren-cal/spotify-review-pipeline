"""Model client: allowlist, shared rate limiter, spend ledger with reservations, bounded retries, per-attempt call log.

Paid calls only happen when provider == "anthropic" and ANTHROPIC_API_KEY is set. Keys are read from the environment
(loaded from .env by the CLI) and are never logged.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import FAKE_MODEL, MODEL_ALLOWLIST, Limits, RoleConfig


class BudgetExceeded(Exception):
    pass


class FatalAPIError(Exception):
    """Non-retryable (auth, permission, bad request). Stops the run."""


class CallFailed(Exception):
    def __init__(self, msg, attempts):
        super().__init__(msg)
        self.attempts = attempts


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SpendLedger:
    """One ledger shared by all workers. Admission requires spent + reserved + next reservation <= cap."""

    def __init__(self, cap_usd: float, already_spent: float = 0.0):
        self.cap = cap_usd
        self.spent = already_spent
        self.reserved = 0.0
        self.unreconciled = 0.0  # timeouts / unknown outcomes, counted conservatively at reservation value
        self._lock = threading.Lock()

    def reserve(self, amount: float) -> float:
        with self._lock:
            if self.spent + self.unreconciled + self.reserved + amount > self.cap:
                raise BudgetExceeded(
                    f"spend cap ${self.cap:.4f} reached: spent ${self.spent:.4f} + unreconciled ${self.unreconciled:.4f} "
                    f"+ reserved ${self.reserved:.4f} + next ${amount:.4f}")
            self.reserved += amount
            return amount

    def settle(self, reservation: float, actual: float | None):
        with self._lock:
            self.reserved -= reservation
            if actual is None:
                self.unreconciled += reservation
            else:
                self.spent += actual

    def snapshot(self) -> dict:
        with self._lock:
            return {"cap_usd": self.cap, "spent_usd": round(self.spent, 6), "reserved_usd": round(self.reserved, 6),
                    "unreconciled_usd": round(self.unreconciled, 6)}


class RateLimiter:
    def __init__(self, requests_per_minute: int):
        self.interval = 60.0 / max(1, requests_per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            t = time.monotonic()
            start = max(t, self._next)
            self._next = start + self.interval
        if start > t:
            time.sleep(start - t)


@dataclass
class ToolResult:
    data: dict | None
    stop_reason: str
    attempts: list = field(default_factory=list)


def usage_cost(model: str, usage: dict, rates: dict) -> float:
    r = rates[model]
    return (usage["uncached_input_tokens"] * r["input"] + usage["cache_write_tokens"] * r["cache_write_5m"]
            + usage["cache_read_tokens"] * r["cache_read"] + usage["output_tokens"] * r["output"])


class LLMClient:
    def __init__(self, provider: str, ledger: SpendLedger, limiter: RateLimiter, rates: dict, limits: Limits,
                 run_id: str, session_id: str, phase: str):
        self.provider = provider
        self.ledger = ledger
        self.limiter = limiter
        self.rates = rates
        self.limits = limits
        self.run_id = run_id
        self.session_id = session_id
        self.phase = phase
        self._drop_params: set = set()
        self._no_forced_tool: set = set()
        self._client = None
        self._rng = random.Random()
        if provider == "anthropic":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise FatalAPIError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
            import anthropic  # imported lazily so offline commands never need the SDK
            self._anthropic = anthropic
            self._client = anthropic.Anthropic(max_retries=0, timeout=limits.request_timeout_s)
        elif provider != "fake":
            raise ValueError("provider must be 'anthropic' or 'fake'")

    # ---------------------------------------------------------------- public
    def model_for(self, cfg: RoleConfig) -> str:
        return FAKE_MODEL if self.provider == "fake" else cfg.model

    def call_tool(self, cfg: RoleConfig, system: str, user: str, tool: dict, review_ids: list[str],
                  label_config: str | None, extra: dict | None = None) -> ToolResult:
        model = self.model_for(cfg)
        if model not in MODEL_ALLOWLIST:
            raise FatalAPIError(f"model {model} not in allowlist")
        est_in = (len(system) + len(user) + len(json.dumps(tool))) // 3 + 50
        reservation_amt = est_in * self.rates[model]["input"] * 1.25 + cfg.max_tokens * self.rates[model]["output"]
        attempts = []
        for attempt in range(1, self.limits.max_attempts + 1):
            reservation = self.ledger.reserve(reservation_amt)  # raises BudgetExceeded before dispatch
            rec = {"request_id": None, "run_id": self.run_id, "session_id": self.session_id, "role": cfg.role,
                   "model": model, "phase": self.phase, "outcome": "failed", "label_config": label_config,
                   "review_ids": list(review_ids), "prompt_version": cfg.prompt_version, "effort": cfg.effort,
                   "thinking": cfg.thinking, "batch_size": len(review_ids), "max_tokens": cfg.max_tokens,
                   "attempt": attempt, "started_at": now_iso(), "input_tokens": 0, "output_tokens": 0,
                   "uncached_input_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0,
                   "cost_usd": 0.0, "cost_status": "no_charge", "stop_reason": None, "error": None,
                   "synthetic_failure": False}
            if extra:
                rec.update(extra)
            t0 = time.monotonic()
            self.limiter.wait()
            try:
                if self.limits.inject_failure_rate and self._rng.random() < self.limits.inject_failure_rate:
                    rec["synthetic_failure"] = True
                    raise _Retryable("injected_transient_failure (synthetic control test; no request sent)", None)
                if self.provider == "fake":
                    data, usage, stop, rid = _fake_call(cfg, system, user, tool)
                else:
                    data, usage, stop, rid = self._anthropic_call(cfg, model, system, user, tool)
                cost = usage_cost(model, usage, self.rates)
                self.ledger.settle(reservation, cost)
                rec.update(usage)
                rec.update({"request_id": rid, "outcome": "succeeded", "stop_reason": stop, "cost_usd": round(cost, 8),
                            "cost_status": "actual_usage", "wall_s": round(time.monotonic() - t0, 3)})
                attempts.append(rec)
                return ToolResult(data, stop, attempts)
            except _Retryable as e:
                rec["wall_s"] = round(time.monotonic() - t0, 3)
                rec["error"] = str(e)[:400]
                rec["request_id"] = e.request_id or f"local-{uuid.uuid4()}"
                if e.unknown_charge:
                    rec["cost_status"] = "unknown_possible_charge"
                    self.ledger.settle(reservation, None)
                else:
                    self.ledger.settle(reservation, 0.0)
                attempts.append(rec)
                if attempt == self.limits.max_attempts:
                    raise CallFailed(f"{cfg.role}: gave up after {attempt} attempts: {e}", attempts)
                delay = e.retry_after if e.retry_after else min(60.0, 2.0 * 2 ** (attempt - 1))
                time.sleep(delay + self._rng.uniform(0, delay * 0.25 + 0.5))
            except FatalAPIError as e:
                rec["wall_s"] = round(time.monotonic() - t0, 3)
                rec["error"] = str(e)[:400]
                rec["request_id"] = getattr(e, "request_id", None) or f"local-{uuid.uuid4()}"
                self.ledger.settle(reservation, 0.0)
                attempts.append(rec)
                e.attempts = attempts
                raise
            except BaseException:
                # e.g. KeyboardInterrupt mid-request: outcome unknown, keep the reservation as unreconciled spend
                self.ledger.settle(reservation, None)
                raise
        raise CallFailed("unreachable", attempts)

    # -------------------------------------------------------------- provider
    def _anthropic_call(self, cfg, model, system, user, tool):
        a = self._anthropic
        forced = model not in self._no_forced_tool
        kwargs = dict(model=model, max_tokens=cfg.max_tokens,
                      system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                      messages=[{"role": "user", "content": user if forced else
                                 user + f"\n\nRespond only by calling the `{tool['name']}` tool."}], tools=[tool],
                      tool_choice={"type": "tool", "name": tool["name"]} if forced else {"type": "auto"})
        if "thinking" not in self._drop_params:
            kwargs["thinking"] = {"type": cfg.thinking}
        if "output_config" not in self._drop_params:
            kwargs["output_config"] = {"effort": cfg.effort}
        if cfg.temperature is not None and "temperature" not in self._drop_params:
            kwargs["temperature"] = cfg.temperature
        try:
            resp = self._client.messages.create(**kwargs)
        except a.RateLimitError as e:
            raise _Retryable(f"429 rate limit: {e}", _rid(e), retry_after=_retry_after(e)) from None
        except a.APITimeoutError as e:
            raise _Retryable(f"timeout: {e}", None, unknown_charge=True) from None
        except a.APIConnectionError as e:
            raise _Retryable(f"connection error: {e}", None, unknown_charge=True) from None
        except a.BadRequestError as e:
            msg = str(e)
            if "tool_choice" in msg and model not in self._no_forced_tool:
                # some models reject forced tool use; fall back to tool_choice=auto + explicit instruction (logged)
                self._no_forced_tool.add(model)
                raise _Retryable(f"400 forced tool_choice unsupported for {model}; retrying with auto: {msg}", _rid(e),
                                 retry_after=0.1) from None
            for p in ("temperature", "output_config", "thinking"):
                if p in msg and p not in self._drop_params:
                    self._drop_params.add(p)  # adapt once to the API's accepted parameters; logged as a failed attempt
                    raise _Retryable(f"400 unsupported parameter {p}; dropping it: {msg}", _rid(e), retry_after=0.1) from None
            err = FatalAPIError(f"400 bad request: {msg}")
            err.request_id = _rid(e)
            raise err from None
        except (a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError) as e:
            err = FatalAPIError(f"{type(e).__name__}: {e}")
            err.request_id = _rid(e)
            raise err from None
        except a.APIStatusError as e:  # 5xx, 529 overloaded
            raise _Retryable(f"{e.status_code}: {e}", _rid(e), retry_after=_retry_after(e)) from None
        u = resp.usage
        usage = {"uncached_input_tokens": u.input_tokens or 0,
                 "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                 "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                 "output_tokens": u.output_tokens or 0}
        usage["input_tokens"] = usage["uncached_input_tokens"] + usage["cache_write_tokens"] + usage["cache_read_tokens"]
        data = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                data = block.input if isinstance(block.input, dict) else None
        rid = getattr(resp, "_request_id", None) or resp.id
        return data, usage, resp.stop_reason, rid


class _Retryable(Exception):
    def __init__(self, msg, request_id, retry_after=None, unknown_charge=False):
        super().__init__(msg)
        self.request_id = request_id
        self.retry_after = retry_after
        self.unknown_charge = unknown_charge


def _rid(e):
    try:
        return e.response.headers.get("request-id")
    except Exception:
        return None


def _retry_after(e):
    try:
        v = e.response.headers.get("retry-after")
        return min(60.0, float(v)) if v else None
    except Exception:
        return None


# ------------------------------------------------------------------- fake provider (offline tests only)
_KW = [
    ("access", "login_failure", ["log in", "login", "sign in", "password", "account"]),
    ("billing", "price_increase_cost", ["price", "expensive", "premium", "pay ", "charged", "subscription"]),
    ("usability", "ads_interruptions", [" ad ", "ads", "advert"]),
    ("downloads", "downloads_disappear", ["download", "offline"]),
    ("playback", "stops_or_pauses", ["stop", "pause", "crash", "skip", "lag", "bluetooth"]),
    ("catalog", "search", ["song", "artist", "lyrics", "playlist", "search"]),
]


def _fake_label(text: str) -> dict:
    t = " " + text.lower() + " "
    topic, sub = "other", "general"
    for tp, sb, kws in _KW:
        if any(k in t for k in kws):
            topic, sub = tp, sb
            break
    neg = any(w in t for w in ["bad", "worst", "hate", "not ", "can't", "cant", "doesn't", "stop", "crash", "annoy", "terrible"])
    pos = any(w in t for w in ["good", "great", "love", "best", "excellent", "amazing", "nice"])
    if any(w in t for w in ["uninstall", "cancel", "switching to", "leaving"]):
        intent, sev, sent = "cancellation", 3, -0.7
    elif neg:
        intent, sev, sent = "complaint", 3 if topic != "other" else 2, -0.6
    elif "please add" in t or "wish" in t:
        intent, sev, sent = "request", 1, 0.1
    elif pos:
        intent, sev, sent = "praise", 1, 0.8
    else:
        intent, sev, sent = "unclear", 1, 0.0
    if intent in ("praise", "unclear") and topic != "other":
        topic, sub = "other", "general"
    quote = "*" if len(text) <= 120 else text[:100]
    return {"topic": topic, "subtopic": sub, "intent": intent, "sentiment": sent, "severity": sev,
            "entities": [], "quote": quote, "needs_review": False, "reason": ""}


# Test hooks (offline only): {"transient": n} raise n retryable errors; {"drop_key": n} omit the first key in n responses;
# {"bad_quote": n} return a non-substring quote for the first item in n responses; {"fatal": True} auth-style failure.
FAKE_FAULTS: dict = {}


def _take(name):
    if FAKE_FAULTS.get(name, 0) > 0:
        FAKE_FAULTS[name] -= 1
        return True
    return False


def _fake_call(cfg: RoleConfig, system: str, user: str, tool: dict):
    if FAKE_FAULTS.get("fatal"):
        raise FatalAPIError("fake 401 authentication error")
    if _take("transient"):
        raise _Retryable("fake 529 overloaded", f"fake-fail-{uuid.uuid4()}", retry_after=0.01)
    payload = json.loads(user.split("INPUT_JSON:\n", 1)[1])
    name = tool["name"]
    if name == "record_labels":
        data = {"items": [{"k": r["k"], **_fake_label(r["text"])} for r in payload]}
        if data["items"] and _take("drop_key"):
            data["items"] = data["items"][1:]
        if data["items"] and _take("bad_quote"):
            data["items"][0]["quote"] = "THIS QUOTE IS NOT IN THE REVIEW"
    elif name == "audit_labels":
        data = {"items": [{"k": r["k"], **{k: v for k, v in _fake_label(r["text"]).items()
                                           if k in ("topic", "intent", "severity", "sentiment")}, "confidence": "medium"}
                          for r in payload]}
    elif name == "name_issues":
        data = {"items": [{"issue_id": i["issue_id"], "name": i["issue_id"].replace(".", " / ").replace("_", " "),
                           "description": "Stub description (offline fake provider).", "coherent": True, "note": ""}
                          for i in payload["issues"]]}
    elif name == "write_memo":
        top = payload["ranking"][0]
        cid = top["claims"]["priority_score"]
        data = {"title": "Offline stub memo", "recommended_area": top["issue_id"].split(".")[0],
                "recommendation": f"Prioritise {top['issue_id']} (priority score {top['priority_score']} [{cid}]).",
                "supporting_evidence": [{"point": f"Top-ranked issue {top['issue_id']} [{cid}].", "claim_ids": [cid],
                                         "issue_ids": [top["issue_id"]], "review_ids": []}],
                "alternatives": [], "dashboard_recommendations": [
                    {"title": "Stub", "detail": f"See {top['issue_id']} [{cid}].", "claim_ids": [cid], "issue_ids": [top["issue_id"]]}],
                "limitations": ["Offline stub output; not a real model memo."]}
    else:
        raise ValueError(name)
    tokens_in = len(system + user) // 4
    tokens_out = len(json.dumps(data)) // 4
    usage = {"uncached_input_tokens": tokens_in, "cache_write_tokens": 0, "cache_read_tokens": 0,
             "output_tokens": tokens_out, "input_tokens": tokens_in}
    return data, usage, "tool_use", f"fake-{uuid.uuid4()}"
