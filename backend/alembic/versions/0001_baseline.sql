CREATE TABLE app.backfill_progress (
	name VARCHAR(128) NOT NULL,
	cursor JSONB NOT NULL,
	status VARCHAR(16) NOT NULL,
	updated_at BIGINT NOT NULL,
	PRIMARY KEY (name)
);
CREATE TABLE app.calendar_backfill_jobs (
	id VARCHAR(64) NOT NULL,
	mode VARCHAR(32) NOT NULL,
	status VARCHAR(16) DEFAULT 'queued' NOT NULL,
	payload JSONB DEFAULT '{}' NOT NULL,
	created_at BIGINT NOT NULL,
	updated_at BIGINT NOT NULL,
	lease_until BIGINT,
	worker_id VARCHAR(128),
	PRIMARY KEY (id)
);
CREATE TABLE app.crawl_runs (
	id BIGSERIAL NOT NULL,
	started_at BIGINT NOT NULL,
	finished_at BIGINT,
	status VARCHAR(16) NOT NULL,
	trigger_source TEXT,
	stats JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (id)
);
CREATE TABLE app.dashboard_state (
	name VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	version BIGINT DEFAULT '0' NOT NULL,
	updated_at BIGINT NOT NULL,
	PRIMARY KEY (name)
);
CREATE TABLE app.data_import_records (
	id UUID NOT NULL,
	source_fingerprint VARCHAR(128) NOT NULL,
	status VARCHAR(16) NOT NULL,
	report JSONB NOT NULL,
	created_at BIGINT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (source_fingerprint)
);
CREATE TABLE app.favorites (
	id VARCHAR(128) NOT NULL,
	owner VARCHAR(128) NOT NULL,
	item_type VARCHAR(64) NOT NULL,
	item JSONB NOT NULL,
	tags JSONB DEFAULT '[]' NOT NULL,
	notes TEXT DEFAULT '' NOT NULL,
	saved_at BIGINT NOT NULL,
	PRIMARY KEY (id)
);
CREATE TABLE app.tracked_up_settings (
	name VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	updated_at BIGINT NOT NULL,
	PRIMARY KEY (name)
);
CREATE TABLE app.tracked_ups (
	mid BIGSERIAL NOT NULL,
	payload JSONB NOT NULL,
	enabled BOOLEAN DEFAULT 'true' NOT NULL,
	updated_at BIGINT NOT NULL,
	PRIMARY KEY (mid)
);
CREATE TABLE app.tracking_requests (
	id VARCHAR(64) NOT NULL,
	mid BIGINT NOT NULL,
	visitor_id VARCHAR(128) NOT NULL,
	status VARCHAR(16) NOT NULL,
	payload JSONB NOT NULL,
	created_at BIGINT NOT NULL,
	reviewed_at BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_tracking_request_state UNIQUE (mid, visitor_id, status)
);
CREATE TABLE app.up_card_cache (
	mid BIGSERIAL NOT NULL,
	payload JSONB NOT NULL,
	fetched_at BIGINT NOT NULL,
	PRIMARY KEY (mid)
);
CREATE TABLE app.ups (
	mid BIGSERIAL NOT NULL,
	name TEXT,
	face TEXT,
	tracked BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (mid)
);
CREATE TABLE app.video_snapshot_documents (
	ts BIGINT NOT NULL,
	field VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	item_count INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (ts, field)
);
CREATE TABLE app.videos (
	bvid VARCHAR(32) NOT NULL,
	mid BIGINT,
	title TEXT,
	tid INTEGER,
	tname TEXT,
	pub_date BIGINT,
	duration INTEGER,
	first_seen BIGINT NOT NULL,
	source TEXT,
	observe_tier VARCHAR(16) DEFAULT 'hot' NOT NULL,
	pic TEXT,
	PRIMARY KEY (bvid)
);
CREATE TABLE app.word_observations (
	word TEXT NOT NULL,
	ts BIGINT NOT NULL,
	scope VARCHAR(32) DEFAULT 'danmaku' NOT NULL,
	count INTEGER NOT NULL,
	PRIMARY KEY (word, ts, scope)
);
CREATE TABLE app.worker_heartbeats (
	worker_id VARCHAR(128) NOT NULL,
	heartbeat_at BIGINT NOT NULL,
	details JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (worker_id)
);
CREATE TABLE auth.admin_accounts (
	mid BIGSERIAL NOT NULL,
	name TEXT DEFAULT '' NOT NULL,
	face TEXT DEFAULT '' NOT NULL,
	added_at BIGINT NOT NULL,
	added_by TEXT DEFAULT '' NOT NULL,
	PRIMARY KEY (mid)
);
CREATE TABLE auth.browser_sessions (
	token VARCHAR(128) NOT NULL,
	visitor_id VARCHAR(128) NOT NULL,
	mid BIGINT,
	name TEXT DEFAULT '' NOT NULL,
	face TEXT DEFAULT '' NOT NULL,
	cookies JSONB DEFAULT '{}' NOT NULL,
	created_at BIGINT NOT NULL,
	expires_at BIGINT NOT NULL,
	PRIMARY KEY (token)
);
CREATE TABLE auth.collector_credential_handoffs (
	id BIGSERIAL NOT NULL,
	action VARCHAR(16) NOT NULL,
	payload JSONB DEFAULT '{}' NOT NULL,
	requested_by VARCHAR(128) NOT NULL,
	requested_at BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_handoff_action CHECK (action IN ('replace', 'delete'))
);
CREATE TABLE app.calendar_backfill_job_items (
	job_id VARCHAR(64) NOT NULL,
	mid BIGINT NOT NULL,
	status VARCHAR(16) DEFAULT 'queued' NOT NULL,
	worker_id VARCHAR(128),
	payload JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (job_id, mid),
	FOREIGN KEY(job_id) REFERENCES app.calendar_backfill_jobs (id) ON DELETE CASCADE
);
CREATE TABLE app.calendar_video_authors (
	bvid VARCHAR(32) NOT NULL,
	mid BIGINT NOT NULL,
	last_seen_at BIGINT NOT NULL,
	missing_count INTEGER DEFAULT '0' NOT NULL,
	status VARCHAR(16) DEFAULT 'active' NOT NULL,
	PRIMARY KEY (bvid, mid),
	FOREIGN KEY(bvid) REFERENCES app.videos (bvid),
	FOREIGN KEY(mid) REFERENCES app.ups (mid)
);
CREATE TABLE app.calendar_videos (
	bvid VARCHAR(32) NOT NULL,
	mid BIGINT NOT NULL,
	pub_date BIGINT NOT NULL,
	pub_date_str VARCHAR(16) NOT NULL,
	views BIGINT DEFAULT '0' NOT NULL,
	title TEXT DEFAULT '' NOT NULL,
	fetched_at BIGINT DEFAULT '0' NOT NULL,
	last_seen_at BIGINT DEFAULT '0' NOT NULL,
	missing_count INTEGER DEFAULT '0' NOT NULL,
	status VARCHAR(16) DEFAULT 'active' NOT NULL,
	PRIMARY KEY (bvid, mid),
	FOREIGN KEY(bvid) REFERENCES app.videos (bvid),
	FOREIGN KEY(mid) REFERENCES app.ups (mid)
);
CREATE TABLE app.up_observations (
	mid BIGINT NOT NULL,
	ts BIGINT NOT NULL,
	payload JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (mid, ts),
	FOREIGN KEY(mid) REFERENCES app.ups (mid)
);
CREATE TABLE app.up_staff_memberships (
	bvid VARCHAR(32) NOT NULL,
	mid BIGINT NOT NULL,
	position INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (bvid, mid),
	FOREIGN KEY(bvid) REFERENCES app.videos (bvid),
	FOREIGN KEY(mid) REFERENCES app.ups (mid)
);
CREATE TABLE app.video_observations (
	bvid VARCHAR(32) NOT NULL,
	ts BIGINT NOT NULL,
	views BIGINT,
	likes BIGINT,
	coins BIGINT,
	favorites BIGINT,
	shares BIGINT,
	comments BIGINT,
	danmaku BIGINT,
	online_count BIGINT,
	online_precision VARCHAR(16),
	potential_score FLOAT,
	PRIMARY KEY (bvid, ts),
	FOREIGN KEY(bvid) REFERENCES app.videos (bvid) ON DELETE CASCADE
);
CREATE TABLE app.video_tags (
	bvid VARCHAR(32) NOT NULL,
	tag TEXT NOT NULL,
	ts BIGINT NOT NULL,
	PRIMARY KEY (bvid, tag),
	FOREIGN KEY(bvid) REFERENCES app.videos (bvid) ON DELETE CASCADE
);
CREATE INDEX idx_browser_sessions_mid ON auth.browser_sessions (mid);
CREATE INDEX idx_browser_sessions_visitor ON auth.browser_sessions (visitor_id);
CREATE INDEX idx_video_observations_ts ON app.video_observations (ts);
