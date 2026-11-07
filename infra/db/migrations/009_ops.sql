-- INF-P5: reason-code catalogue (T03), metrics (T02), job queue (T05), structured journal lines (T01).

-- migrate:up
CREATE TABLE ops.reason_code (
  code text PRIMARY KEY,
  layer text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('fire', 'skip', 'block')),
  meaning text NOT NULL
);

CREATE TABLE ops.metric (
  ts timestamptz NOT NULL,
  name text NOT NULL,
  subject text NOT NULL,          -- asset, run or '*'
  value double precision,
  status text CHECK (status IN ('ok', 'warn', 'alarm')),
  detail text,
  PRIMARY KEY (ts, name, subject)
);
CREATE INDEX metric_name_subject ON ops.metric (name, subject, ts DESC);

-- Postgres-backed queue: workers take jobs with FOR UPDATE SKIP LOCKED.
CREATE TABLE ops.job (
  job_id bigserial PRIMARY KEY,
  command text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
  enqueued_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  worker text,
  exit_code integer,
  log_path text
);
CREATE INDEX job_queued ON ops.job (status, job_id);

-- Tester journal lines with correlation ids (run segment, event_id where the line names a setup-day).
CREATE TABLE raw.journal_line (
  file_sha256 text NOT NULL,
  line_no integer NOT NULL,
  run_seq integer,
  symbol text,
  ea_version text,
  sim_time timestamp,
  event_id text,
  kind text,
  message text NOT NULL,
  PRIMARY KEY (file_sha256, line_no)
);
CREATE INDEX journal_line_event ON raw.journal_line (event_id) WHERE event_id IS NOT NULL;

-- migrate:down
DROP TABLE raw.journal_line;
DROP TABLE ops.job;
DROP TABLE ops.metric;
DROP TABLE ops.reason_code;
