"""Shared constants, hashing and I/O helpers. Standard library only."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterable, Iterator

FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
# Precedence order from the grading contract.
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
RANKED_INTENTS = ("complaint", "cancellation")
SAMPLE_SEED = "berkeley-fall-2026-assignment-5-v1"
FULL_SHA256 = "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6"
FULL_ROWS = 660622
FULL_NONEMPTY = 660609

# Optional custom subtopics. Issue IDs are "<topic>.<subtopic>"; the common topic is unchanged.
SUBTOPICS = {
    "access": ["login_failure", "logged_out", "signup_or_verification", "password_reset", "account_hacked_or_lost", "other"],
    "usability": ["ads_interruptions", "ui_redesign_navigation", "shuffle_queue_controls", "playlist_library_management",
                  "widgets_lockscreen_car", "other"],
    "playback": ["stops_or_pauses", "crashes_or_wont_open", "lag_slow_loading", "connectivity_bluetooth_cast",
                 "audio_quality_volume", "battery_storage_resources", "other"],
    "downloads": ["downloads_disappear", "cannot_download", "offline_mode_fails", "other"],
    "catalog": ["missing_or_removed_content", "search", "recommendations_algorithm", "lyrics", "podcasts_audiobooks", "other"],
    "billing": ["price_increase_cost", "unexpected_charges_refunds", "premium_not_recognized", "free_tier_restrictions_paywall",
                "plan_management_family_student", "other"],
    "support": ["no_response_or_unhelpful", "other"],
    "other": ["general", "unrelated_or_unclear"],
}


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def row_sha(row: dict) -> str:
    """Identical to check_submission.row_sha: exact strings, no normalization."""
    return hashlib.sha256(canonical([row[k] for k in FIELDS]).encode("utf-8")).hexdigest()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sample_rank(review_id: str) -> int:
    """Manifest sampling order: lowest SHA-256(seed:id) first (golden 50, then analysis 10,000)."""
    return int.from_bytes(hashlib.sha256((SAMPLE_SEED + ":" + review_id).encode()).digest(), "big")


def csv_rows(path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        missing = [k for k in FIELDS if k not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing required columns {missing}")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"{path}: malformed CSV row near review_id={row.get('review_id')}")
            yield {k: row[k] for k in FIELDS}


def mean_string(total: int, n: int) -> str:
    return str((Decimal(total) / Decimal(n)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def atomic_write_text(path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path, value) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path, rows: Iterable[dict], gz: bool = False) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    n = 0
    opener = (lambda p: gzip.open(p, "wt", encoding="utf-8", compresslevel=6)) if gz else (lambda p: open(p, "w", encoding="utf-8"))
    with opener(tmp) as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
            n += 1
    os.replace(tmp, path)
    return n


def read_jsonl(path) -> Iterator[dict]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_csv(path, header, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)
