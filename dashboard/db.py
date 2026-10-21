"""Database schema shared by the loader and the API. DATABASE_URL: postgres (deployed) or sqlite (local default)."""
import os

from sqlalchemy import (JSON, Boolean, Column, Float, Integer, MetaData, String, Table, Text, create_engine)

meta = MetaData()

records = Table("records", meta,
                Column("review_id", String(64), primary_key=True),
                Column("review_timestamp", String(32)), Column("review_rating", String(4)),
                Column("app_version", String(32)), Column("topic", String(16), index=True),
                Column("subtopic", String(48)), Column("intent", String(16), index=True),
                Column("sentiment", Float), Column("severity", Integer), Column("needs_review", Boolean),
                Column("evidence_quote", Text), Column("cache_source_id", String(64)),
                Column("label_config", String(160)), Column("issue_id", String(64), index=True))

issues = Table("issues", meta,
               Column("issue_id", String(64), primary_key=True), Column("rank", Integer), Column("area", String(32)),
               Column("name", Text), Column("description", Text), Column("complaint_count", Integer),
               Column("cancellation_count", Integer), Column("severity_sum", Integer), Column("mean_severity", String(16)),
               Column("priority_score", Integer), Column("share_pct", String(16)), Column("needs_review_count", Integer),
               Column("model_coherent", Boolean), Column("model_note", Text))

areas = Table("areas", meta,
              Column("area", String(32), primary_key=True), Column("completed_records", Integer),
              Column("complaint_count", Integer), Column("cancellation_count", Integer), Column("severity_sum", Integer),
              Column("mean_severity", String(16)), Column("share_pct", String(16)), Column("severity_4_plus", Integer),
              Column("severity_4_plus_pct", String(16)))

trends = Table("trends", meta,
               Column("month", String(8), primary_key=True), Column("area", String(32), primary_key=True),
               Column("complaints", Integer), Column("completed_in_month", Integer), Column("share_pct", String(16)))

claims = Table("claims", meta,
               Column("claim_id", String(8), primary_key=True), Column("issue_id", String(64)),
               Column("metric", String(32)), Column("value", String(32)), Column("cited_in_memo", Boolean))

facts = Table("facts", meta,
              Column("fact_id", String(8), primary_key=True), Column("scope", String(32)),
              Column("metric", String(64)), Column("value", String(32)))

documents = Table("documents", meta, Column("key", String(64), primary_key=True), Column("body", JSON))


def engine():
    url = os.environ.get("DATABASE_URL") or "sqlite:///" + os.path.join(os.path.dirname(__file__), "dashboard.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True)
