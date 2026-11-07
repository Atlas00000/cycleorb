-- INF-P2: contract 1.1.0 (run.kind + 'live', decision.reason + 'guard'), incremental-ingest state, data-quality
-- results, and the source commit of imported files (Ouroboros). infra/db/contract_ddl.sql holds the contract's
-- full DDL; `corb db check` compares the live columns with the contract.

-- migrate:up
ALTER TABLE core.run DROP CONSTRAINT run_kind_check;
ALTER TABLE core.run ADD CONSTRAINT run_kind_check CHECK (kind IN ('baseline', 'variant', 'reference', 'live'));
ALTER TABLE core.decision DROP CONSTRAINT decision_reason_check;
ALTER TABLE core.decision ADD CONSTRAINT decision_reason_check CHECK (reason IN ('atr_band_low', 'atr_band_high',
  'vol_floor', 'cost_cap', 'last_day', 'warmup', 'missing_bars', 'price_through', 'already_traded', 'skip_date',
  'other', 'guard'));

ALTER TABLE raw.source_file ADD COLUMN source_commit text;

CREATE TABLE ops.ingest_state (
  run_key text PRIMARY KEY REFERENCES core.run (run_key) ON DELETE CASCADE,
  content_sha256 text NOT NULL,
  ingested_at timestamptz NOT NULL
);

CREATE TABLE ops.dq_result (
  check_id text NOT NULL,
  run_key text NOT NULL,
  status text NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
  value double precision,
  detail text,
  checked_at timestamptz NOT NULL,
  PRIMARY KEY (check_id, run_key)
);

-- migrate:down
DROP TABLE ops.dq_result;
DROP TABLE ops.ingest_state;
ALTER TABLE raw.source_file DROP COLUMN source_commit;
ALTER TABLE core.decision DROP CONSTRAINT decision_reason_check;
ALTER TABLE core.decision ADD CONSTRAINT decision_reason_check CHECK (reason IN ('atr_band_low', 'atr_band_high',
  'vol_floor', 'cost_cap', 'last_day', 'warmup', 'missing_bars', 'price_through', 'already_traded', 'skip_date',
  'other'));
ALTER TABLE core.run DROP CONSTRAINT run_kind_check;
ALTER TABLE core.run ADD CONSTRAINT run_kind_check CHECK (kind IN ('baseline', 'variant', 'reference'));
