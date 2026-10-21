"""Output schema for model roles and code-side validation of every returned item."""
from __future__ import annotations

import math
import re

from .common import INTENTS, SUBTOPICS, TOPICS

ALL_SUBTOPICS = sorted({s for v in SUBTOPICS.values() for s in v})

ENRICH_TOOL = {
    "name": "record_labels",
    "description": "Record one label set per review key.",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "k": {"type": "string"},
                "topic": {"type": "string", "enum": list(TOPICS)},
                "subtopic": {"type": "string", "enum": ALL_SUBTOPICS},
                "intent": {"type": "string", "enum": list(INTENTS)},
                "sentiment": {"type": "number"},
                "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "entities": {"type": "array", "items": {"type": "string"}},
                "quote": {"type": "string"},
                "needs_review": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["k", "topic", "subtopic", "intent", "sentiment", "severity", "entities", "quote", "needs_review", "reason"],
        }}},
        "required": ["items"],
    },
}

VERIFY_TOOL = {
    "name": "audit_labels",
    "description": "Record independent audit labels, one per review key.",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "k": {"type": "string"},
                "topic": {"type": "string", "enum": list(TOPICS)},
                "intent": {"type": "string", "enum": list(INTENTS)},
                "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "sentiment": {"type": "number"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["k", "topic", "intent", "severity", "sentiment", "confidence"],
        }}},
        "required": ["items"],
    },
}

GROUP_TOOL = {
    "name": "name_issues",
    "description": "Name and sanity-check each candidate issue.",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"issue_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
                           "coherent": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["issue_id", "name", "description", "coherent", "note"]}}},
        "required": ["items"],
    },
}

AREAS = ["access", "usability", "playback", "billing_support", "downloads", "catalog"]

MEMO_TOOL = {
    "name": "write_memo",
    "description": "Write the decision memo as structured fields.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "recommended_area": {"type": "string", "enum": AREAS},
            "recommendation": {"type": "string", "description": "2-4 sentence recommendation with [ID] citations after every number."},
            "supporting_evidence": {"type": "array", "items": {"type": "object", "properties": {
                "point": {"type": "string"}, "claim_ids": {"type": "array", "items": {"type": "string"}},
                "issue_ids": {"type": "array", "items": {"type": "string"}},
                "review_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["point", "claim_ids", "issue_ids", "review_ids"]}},
            "alternatives": {"type": "array", "items": {"type": "object", "properties": {
                "area": {"type": "string", "enum": AREAS}, "assessment": {"type": "string"},
                "claim_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["area", "assessment", "claim_ids"]}},
            "dashboard_recommendations": {"type": "array", "description": "3-5 concrete actions for the dashboard.",
                                          "items": {"type": "object", "properties": {
                                              "title": {"type": "string"}, "detail": {"type": "string"},
                                              "claim_ids": {"type": "array", "items": {"type": "string"}},
                                              "issue_ids": {"type": "array", "items": {"type": "string"}}},
                                              "required": ["title", "detail", "claim_ids", "issue_ids"]}},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "recommended_area", "recommendation", "supporting_evidence", "alternatives",
                     "dashboard_recommendations", "limitations"],
    },
}


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def resolve_quote(quote: str, text: str):
    """Return (exact_source_substring, note) or (None, reason). Never invents text: the result is always a slice of `text`."""
    if not isinstance(quote, str):
        return None, "quote_not_string"
    q = quote.strip()
    if q in ("*", "") or q == text.strip():
        return (text.strip() or text), ("full_text" if q in ("*", "") else None)
    if q in text:
        return q, None
    q2 = q.strip("\"'“”‘’ ").rstrip(".…").strip()
    if q2 and q2 in text:
        return q2, "quote_trimmed"
    # whitespace-insensitive match mapped back onto the original characters
    if q2:
        pattern = r"\s+".join(re.escape(part) for part in q2.split())
        m = re.search(pattern, text) or re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0), "quote_whitespace_or_case_mapped"
    # deterministic extraction: a short review's complete original text is a valid evidence quote
    if len(text) <= 300 and text.strip():
        return text.strip(), "quote_replaced_with_full_text"
    return None, "quote_not_in_source"


def validate_enrich_item(item: dict, text: str):
    """Returns (clean_record, None) or (None, reason)."""
    if not isinstance(item, dict):
        return None, "item_not_object"
    topic, intent = item.get("topic"), item.get("intent")
    if topic not in TOPICS:
        return None, f"bad_topic:{topic}"
    if intent not in INTENTS:
        return None, f"bad_intent:{intent}"
    sev = item.get("severity")
    if isinstance(sev, float) and sev.is_integer():
        sev = int(sev)
    if type(sev) is not int or not 1 <= sev <= 5:
        return None, f"bad_severity:{sev}"
    sent = item.get("sentiment")
    if isinstance(sent, str):
        try:
            sent = float(sent)
        except ValueError:
            pass
    if isinstance(sev, str) and sev.strip().isdigit():
        sev = int(sev)
    if type(sent) not in (int, float) or not math.isfinite(sent) or not -1 <= sent <= 1:
        return None, f"bad_sentiment:{sent}"
    quote, qnote = resolve_quote(item.get("quote"), text)
    if quote is None:
        return None, qnote
    ents = item.get("entities")
    if ents is None or ents == "":
        ents = []
    if isinstance(ents, str):
        ents = [e for e in ents.split(",")]
    if not isinstance(ents, list):
        return None, "bad_entities"
    ents = [e.strip() for e in ents if isinstance(e, str) and e.strip()][:6]
    notes = [qnote] if qnote else []
    sub = item.get("subtopic")
    if sub not in SUBTOPICS[topic]:
        notes.append(f"subtopic_mapped_to_other:{sub}")
        sub = "other" if "other" in SUBTOPICS[topic] else "general"
    needs = item.get("needs_review")
    if isinstance(needs, str) and needs.strip().lower() in ("true", "false"):
        needs = needs.strip().lower() == "true"
    if type(needs) is not bool:
        return None, "bad_needs_review"
    reason = item.get("reason") if isinstance(item.get("reason"), str) else ""
    # Consistency with the shared severity rubric: flag (never silently rewrite) contradictions.
    if intent in ("praise", "unclear", "request") and sev > 1 or intent in ("complaint", "cancellation") and sev == 1:
        if intent != "cancellation":
            needs = True
            reason = (reason + "; " if reason else "") + "intent/severity inconsistent"
            notes.append("intent_severity_inconsistent")
    return {"topic": topic, "subtopic": sub, "intent": intent, "sentiment": round(float(sent), 3), "severity": sev,
            "entities": ents, "evidence_quote": quote, "needs_review": needs, "review_reason": reason[:200],
            "notes": ";".join(notes)}, None


def validate_verify_item(item: dict):
    if not isinstance(item, dict):
        return None
    if item.get("topic") not in TOPICS or item.get("intent") not in INTENTS:
        return None
    sev = item.get("severity")
    if isinstance(sev, float) and sev.is_integer():
        sev = int(sev)
    if type(sev) is not int or not 1 <= sev <= 5:
        return None
    sent = item.get("sentiment")
    if isinstance(sent, str):
        try:
            sent = float(sent)
        except ValueError:
            pass
    if isinstance(sev, str) and sev.strip().isdigit():
        sev = int(sev)
    if type(sent) not in (int, float) or not -1 <= sent <= 1:
        sent = None
    return {"topic": item["topic"], "intent": item["intent"], "severity": sev, "sentiment": sent,
            "confidence": item.get("confidence") if item.get("confidence") in ("low", "medium", "high") else "medium"}
