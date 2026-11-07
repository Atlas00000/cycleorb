-- INF-P3-T02: bar lake index and calendar snapshots (bars themselves stay in parquet under var/lake/bars).

-- migrate:up
CREATE TABLE features.bar_index (
  symbol text NOT NULL,
  tf text NOT NULL CHECK (tf IN ('M1', 'M5', 'H1', 'D1')),
  year integer NOT NULL,
  rows integer NOT NULL CHECK (rows >= 0),
  first_bar timestamptz NOT NULL,
  last_bar timestamptz NOT NULL,
  lake_path text NOT NULL,
  sha256 text NOT NULL,
  source text NOT NULL,
  exported_at timestamptz NOT NULL,
  PRIMARY KEY (symbol, tf, year, source)
);

CREATE TABLE features.calendar_snapshot (
  snapshot_sha256 text PRIMARY KEY,
  events integer NOT NULL,
  first_event timestamptz,
  last_event timestamptz,
  taken_at timestamptz NOT NULL
);

-- migrate:down
DROP TABLE features.calendar_snapshot;
DROP TABLE features.bar_index;
