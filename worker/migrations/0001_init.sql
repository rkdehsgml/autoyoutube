-- worker/migrations/0001_init.sql (Worker·에이전트 공용, D1 스키마 단일 기준)
-- 로컬(SqliteStore)과 테스트도 이 파일을 그대로 SQLite에 올려 쓴다.
CREATE TABLE settings (
  key   TEXT PRIMARY KEY,   -- daily_quota, paused, job_budget_usd, monthly_budget_usd, platforms
  value TEXT NOT NULL
);

CREATE TABLE topics (
  id           TEXT PRIMARY KEY,          -- ULID
  title        TEXT NOT NULL,
  norm_hash    TEXT NOT NULL UNIQUE,      -- 중복 방지
  source       TEXT NOT NULL,             -- youtube | naver | web | manual
  angle        TEXT,
  evidence_url TEXT,
  score        REAL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'new',  -- new | used | rejected
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE jobs (
  id              TEXT PRIMARY KEY,       -- ULID, Worker가 발급
  origin          TEXT NOT NULL,          -- cron | telegram | manual | redo
  topic_id        TEXT REFERENCES topics(id),
  requested_topic TEXT,                   -- /new 로 받은 원문
  format_id       TEXT,
  config_version  TEXT,                   -- 실행한 코드의 git sha
  state           TEXT NOT NULL DEFAULT 'queued',
  attempt         INTEGER NOT NULL DEFAULT 0,
  qa_rounds       INTEGER NOT NULL DEFAULT 0,
  lease_owner     TEXT,                   -- GitHub run id
  lease_until     TEXT,
  cost_usd        REAL NOT NULL DEFAULT 0,
  error           TEXT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_jobs_state ON jobs(state, updated_at);

CREATE TABLE step_runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id       TEXT NOT NULL REFERENCES jobs(id),
  step         TEXT NOT NULL,             -- researching ... publishing
  role         TEXT,                      -- 결정론 단계면 NULL
  status       TEXT NOT NULL,             -- started | ok | failed
  input_hash   TEXT,
  cost_usd     REAL DEFAULT 0,
  tokens_in    INTEGER,
  tokens_out   INTEGER,
  gh_run_id    TEXT,
  started_at   TEXT,
  ended_at     TEXT,
  error        TEXT
);

CREATE TABLE artifacts (
  job_id       TEXT NOT NULL REFERENCES jobs(id),
  kind         TEXT NOT NULL,             -- research | storyboard | manifest | audio | visual | subs | final | thumb | qa | meta
  scene        INTEGER NOT NULL DEFAULT -1,
  r2_key       TEXT NOT NULL,
  provider     TEXT,
  cost_usd     REAL DEFAULT 0,
  checks       TEXT,                      -- JSON: ratio_ok, text_ok, issues
  content_hash TEXT,
  PRIMARY KEY (job_id, kind, scene)
);

CREATE TABLE evals (
  job_id         TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  item           TEXT NOT NULL,           -- hook | insight | accuracy | av_match | subtitle | audio | policy
  score          REAL NOT NULL,
  judge          TEXT NOT NULL,           -- llm | gemini | rule | human
  note           TEXT,
  PRIMARY KEY (job_id, rubric_version, item, judge)
);

CREATE TABLE decisions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id     TEXT,
  role       TEXT NOT NULL,
  action     TEXT NOT NULL,
  reason     TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE approvals (
  job_id     TEXT PRIMARY KEY REFERENCES jobs(id),
  decision   TEXT NOT NULL,               -- approved | rejected | redo
  reason     TEXT,
  decided_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE publications (
  job_id       TEXT NOT NULL,
  platform     TEXT NOT NULL,             -- youtube | instagram | naver_kit
  post_id      TEXT,
  status       TEXT NOT NULL,             -- pending | ok | failed
  published_at TEXT,
  error        TEXT,
  PRIMARY KEY (job_id, platform)          -- 중복 게시 방지
);

CREATE TABLE metrics (
  job_id        TEXT NOT NULL,
  platform      TEXT NOT NULL,
  span          TEXT NOT NULL,            -- 48h | 7d
  views         INTEGER,
  engaged_views INTEGER,
  avg_view_pct  REAL,
  subs_gained   INTEGER,
  likes         INTEGER,
  shares        INTEGER,
  comments      INTEGER,
  captured_at   TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (job_id, platform, span)
);

CREATE TABLE config_versions (
  version    TEXT PRIMARY KEY,            -- git sha
  change     TEXT,
  pr_number  INTEGER,
  eval_score REAL,
  merged_at  TEXT
);

CREATE TABLE events (                     -- dispatch 실패·알림 등 감사 로그
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,
  payload    TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
