-- INF-P1-T02: named schemas (doc/infrascaleup.md §6) and the landing register.
-- Tables are added by the phase that first writes them (train / score in INF-P4, ops in INF-P2 / P5).

-- migrate:up
CREATE SCHEMA raw;
CREATE SCHEMA core;
CREATE SCHEMA features;
CREATE SCHEMA train;
CREATE SCHEMA score;
CREATE SCHEMA ops;

CREATE TABLE raw.source_file (
  file_sha256 text PRIMARY KEY CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  origin text NOT NULL,
  kind text NOT NULL,
  src_path text NOT NULL,
  landed_path text NOT NULL,
  bytes bigint NOT NULL CHECK (bytes >= 0),
  landed_at timestamptz NOT NULL
);

-- migrate:down
DROP SCHEMA ops CASCADE;
DROP SCHEMA score CASCADE;
DROP SCHEMA train CASCADE;
DROP SCHEMA features CASCADE;
DROP SCHEMA core CASCADE;
DROP SCHEMA raw CASCADE;
