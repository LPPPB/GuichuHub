"""PostgreSQL metadata for the V3 application and authentication schemas."""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData()


def app_table(name, *columns, **kwargs):
    return Table(name, Base.metadata, *columns, schema="app", **kwargs)


def auth_table(name, *columns, **kwargs):
    return Table(name, Base.metadata, *columns, schema="auth", **kwargs)


videos = app_table("videos", Column("bvid", String(32), primary_key=True), Column("mid", BigInteger), Column("title", Text), Column("tid", Integer), Column("tname", Text), Column("pub_date", BigInteger), Column("duration", Integer), Column("first_seen", BigInteger, nullable=False), Column("source", Text), Column("observe_tier", String(16), nullable=False, server_default="hot"), Column("pic", Text))
ups = app_table("ups", Column("mid", BigInteger, primary_key=True), Column("name", Text), Column("face", Text), Column("tracked", Boolean, nullable=False, server_default="false"))
video_observations = app_table("video_observations", Column("bvid", String(32), ForeignKey("app.videos.bvid", ondelete="CASCADE"), primary_key=True), Column("ts", BigInteger, primary_key=True), Column("views", BigInteger), Column("likes", BigInteger), Column("coins", BigInteger), Column("favorites", BigInteger), Column("shares", BigInteger), Column("comments", BigInteger), Column("danmaku", BigInteger), Column("online_count", BigInteger), Column("online_precision", String(16)), Column("potential_score", Float))
Index("idx_video_observations_ts", video_observations.c.ts)
video_tags = app_table("video_tags", Column("bvid", String(32), ForeignKey("app.videos.bvid", ondelete="CASCADE"), primary_key=True), Column("tag", Text, primary_key=True), Column("ts", BigInteger, nullable=False))
word_observations = app_table("word_observations", Column("word", Text, primary_key=True), Column("ts", BigInteger, primary_key=True), Column("scope", String(32), primary_key=True, server_default="danmaku"), Column("count", Integer, nullable=False))
crawl_runs = app_table("crawl_runs", Column("id", BigInteger, primary_key=True, autoincrement=True), Column("started_at", BigInteger, nullable=False), Column("finished_at", BigInteger), Column("status", String(16), nullable=False), Column("trigger_source", Text), Column("stats", JSONB, nullable=False, server_default="{}"))
up_observations = app_table("up_observations", Column("mid", BigInteger, ForeignKey("app.ups.mid"), primary_key=True), Column("ts", BigInteger, primary_key=True), Column("payload", JSONB, nullable=False, server_default="{}"))
up_staff_memberships = app_table("up_staff_memberships", Column("bvid", String(32), ForeignKey("app.videos.bvid"), primary_key=True), Column("mid", BigInteger, ForeignKey("app.ups.mid"), primary_key=True), Column("position", Integer, nullable=False, server_default="0"))
video_snapshot_documents = app_table("video_snapshot_documents", Column("ts", BigInteger, primary_key=True), Column("field", String(64), primary_key=True), Column("payload", JSONB, nullable=False), Column("item_count", Integer, nullable=False, server_default="0"))
calendar_videos = app_table("calendar_videos", Column("bvid", String(32), ForeignKey("app.videos.bvid"), primary_key=True), Column("mid", BigInteger, ForeignKey("app.ups.mid"), nullable=False), Column("pub_date", BigInteger, nullable=False), Column("pub_date_str", String(16), nullable=False), Column("views", BigInteger, nullable=False, server_default="0"), Column("title", Text, nullable=False, server_default=""), Column("fetched_at", BigInteger, nullable=False, server_default="0"), Column("last_seen_at", BigInteger, nullable=False, server_default="0"), Column("missing_count", Integer, nullable=False, server_default="0"), Column("status", String(16), nullable=False, server_default="active"))
calendar_video_authors = app_table("calendar_video_authors", Column("bvid", String(32), ForeignKey("app.videos.bvid"), primary_key=True), Column("mid", BigInteger, ForeignKey("app.ups.mid"), primary_key=True), Column("last_seen_at", BigInteger, nullable=False), Column("missing_count", Integer, nullable=False, server_default="0"), Column("status", String(16), nullable=False, server_default="active"))
calendar_backfill_jobs = app_table("calendar_backfill_jobs", Column("id", String(64), primary_key=True), Column("mode", String(32), nullable=False), Column("status", String(16), nullable=False, server_default="queued"), Column("payload", JSONB, nullable=False, server_default="{}"), Column("created_at", BigInteger, nullable=False), Column("updated_at", BigInteger, nullable=False), Column("lease_until", BigInteger), Column("worker_id", String(128)))
calendar_backfill_job_items = app_table("calendar_backfill_job_items", Column("job_id", String(64), ForeignKey("app.calendar_backfill_jobs.id", ondelete="CASCADE"), primary_key=True), Column("mid", BigInteger, primary_key=True), Column("status", String(16), nullable=False, server_default="queued"), Column("worker_id", String(128)), Column("payload", JSONB, nullable=False, server_default="{}"))
up_analysis_jobs = app_table(
    "up_analysis_jobs",
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("status", String(16), nullable=False, server_default="queued"),
    Column("requested_by", Text, nullable=False),
    Column("roster", JSONB, nullable=False),
    Column("progress", JSONB, nullable=False, server_default="{}"),
    Column("result_summary", JSONB, nullable=False, server_default="{}"),
    Column("error", JSONB),
    Column("created_at", BigInteger, nullable=False),
    Column("started_at", BigInteger),
    Column("updated_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger),
    Column("worker_id", String(128)),
    Column("lease_until", BigInteger),
    Column("fencing_token", BigInteger, nullable=False, server_default="0"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("batch_ts", BigInteger),
    CheckConstraint("status IN ('queued','running','finalizing','succeeded','partial','failed')", name="ck_up_analysis_status"),
)
# A constant expression indexes the shared analysis resource, not each status.
Index("uq_up_analysis_active", sql_text("(1)"), unique=True,
      postgresql_where=up_analysis_jobs.c.status.in_(("queued", "running", "finalizing")),
      _table=up_analysis_jobs)
dashboard_state = app_table("dashboard_state", Column("name", String(64), primary_key=True), Column("payload", JSONB, nullable=False), Column("version", BigInteger, nullable=False, server_default="0"), Column("updated_at", BigInteger, nullable=False))
favorites = app_table("favorites", Column("id", String(128), primary_key=True), Column("owner", String(128), nullable=False), Column("item_type", String(64), nullable=False), Column("item", JSONB, nullable=False), Column("tags", JSONB, nullable=False, server_default="[]"), Column("notes", Text, nullable=False, server_default=""), Column("saved_at", BigInteger, nullable=False))
tracked_ups = app_table("tracked_ups", Column("mid", BigInteger, primary_key=True), Column("payload", JSONB, nullable=False), Column("enabled", Boolean, nullable=False, server_default="true"), Column("updated_at", BigInteger, nullable=False))
tracked_up_settings = app_table("tracked_up_settings", Column("name", String(64), primary_key=True), Column("payload", JSONB, nullable=False), Column("updated_at", BigInteger, nullable=False))
tracking_requests = app_table("tracking_requests", Column("id", String(64), primary_key=True), Column("mid", BigInteger, nullable=False), Column("visitor_id", String(128), nullable=False), Column("status", String(16), nullable=False), Column("payload", JSONB, nullable=False), Column("created_at", BigInteger, nullable=False), Column("reviewed_at", BigInteger))
Index("uq_tracking_request_active", tracking_requests.c.mid, tracking_requests.c.visitor_id, unique=True, postgresql_where=tracking_requests.c.status == "pending")
up_card_cache = app_table("up_card_cache", Column("mid", BigInteger, primary_key=True), Column("payload", JSONB, nullable=False), Column("fetched_at", BigInteger, nullable=False))
data_import_records = app_table("data_import_records", Column("id", UUID(as_uuid=False), primary_key=True), Column("source_fingerprint", String(128), nullable=False, unique=True), Column("status", String(16), nullable=False), Column("report", JSONB, nullable=False), Column("created_at", BigInteger, nullable=False))
backfill_progress = app_table("backfill_progress", Column("name", String(128), primary_key=True), Column("cursor", JSONB, nullable=False), Column("status", String(16), nullable=False), Column("updated_at", BigInteger, nullable=False), Column("claim_owner", String(128)), Column("lease_until", BigInteger), Column("fencing_token", BigInteger, nullable=False, server_default="0"))
worker_heartbeats = app_table("worker_heartbeats", Column("worker_id", String(128), primary_key=True), Column("heartbeat_at", BigInteger, nullable=False), Column("details", JSONB, nullable=False, server_default="{}"))

admin_accounts = auth_table("admin_accounts", Column("mid", BigInteger, primary_key=True), Column("name", Text, nullable=False, server_default=""), Column("face", Text, nullable=False, server_default=""), Column("added_at", BigInteger, nullable=False), Column("added_by", Text, nullable=False, server_default=""))
browser_sessions = auth_table("browser_sessions", Column("token", String(128), primary_key=True), Column("visitor_id", String(128), nullable=False), Column("mid", BigInteger), Column("name", Text, nullable=False, server_default=""), Column("face", Text, nullable=False, server_default=""), Column("cookies", JSONB, nullable=False, server_default="{}"), Column("created_at", BigInteger, nullable=False), Column("expires_at", BigInteger, nullable=False))
Index("idx_browser_sessions_visitor", browser_sessions.c.visitor_id)
Index("idx_browser_sessions_mid", browser_sessions.c.mid)
collector_credential_handoffs = auth_table("collector_credential_handoffs", Column("id", BigInteger, primary_key=True, autoincrement=True), Column("action", String(16), nullable=False), Column("payload", JSONB, nullable=False, server_default="{}"), Column("requested_by", String(128), nullable=False), Column("requested_at", BigInteger, nullable=False), CheckConstraint("action IN ('replace', 'delete')", name="ck_handoff_action"))
