-- INF-P3: feature registry (T01), regime tape (T05), regime-cell BM (T06).

-- migrate:up
CREATE TABLE features.feature_def (
  feature text NOT NULL,
  version integer NOT NULL,
  dtype text NOT NULL CHECK (dtype IN ('number', 'integer', 'boolean', 'string')),
  unit text,
  as_of text NOT NULL,
  offline boolean NOT NULL,
  definition text NOT NULL,
  PRIMARY KEY (feature, version)
);

-- One row per evaluated setup-day of an asset (armed or skipped), deterministic tags only.
CREATE TABLE features.regime_tape (
  asset text NOT NULL,
  local_day date NOT NULL,
  setup text NOT NULL CHECK (setup IN ('LON', 'NY', 'TKY')),
  tagger_version integer NOT NULL,
  source_run_key text NOT NULL,
  feature_run_key text,
  decision text NOT NULL CHECK (decision IN ('ARMED', 'SKIP')),
  reason text,
  range_atr_pct double precision,
  range_atr_tercile text CHECK (range_atr_tercile IN ('narrow', 'mid', 'wide')),
  vol_pct double precision,
  vol_tercile text CHECK (vol_tercile IN ('low', 'mid', 'high')),
  trend_side integer CHECK (trend_side IN (-1, 0, 1)),
  er50 double precision,
  ev_tier1_entry integer,
  ev_tier1_hold integer,
  opex boolean,
  quad_witching boolean,
  us_open_in_hold boolean,
  PRIMARY KEY (asset, local_day, setup, tagger_version)
);

-- BM per regime cell (CO-09: qualifying n >= 15), on the actual and the shadow outcome streams.
CREATE TABLE score.cell_bm (
  dataset text NOT NULL,
  asset text NOT NULL,
  dim text NOT NULL,
  value text NOT NULL,
  stream text NOT NULL CHECK (stream IN ('actual', 'shadow')),
  n integer NOT NULL,
  wr double precision,
  r_payoff double precision,
  bm double precision,
  mean_r double precision,
  m double precision,
  qualifying boolean NOT NULL,
  bm_nonpos boolean,
  computed_at timestamptz NOT NULL,
  PRIMARY KEY (dataset, asset, dim, value, stream)
);

-- migrate:down
DROP TABLE score.cell_bm;
DROP TABLE features.regime_tape;
DROP TABLE features.feature_def;
