-- INF-P4: datasets, model registry (never overwritten), evaluation runs and every shadow decision.

-- migrate:up
CREATE TABLE train.dataset (
  dataset_id text PRIMARY KEY,
  source text NOT NULL,
  rows integer NOT NULL,
  label text NOT NULL,
  window_from date,
  window_to date,
  sha256 text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE train.model_version (
  model_semver text PRIMARY KEY,
  family text NOT NULL,
  params jsonb NOT NULL,
  features jsonb NOT NULL,
  dataset_id text NOT NULL REFERENCES train.dataset (dataset_id),
  policy_sha256 text NOT NULL,
  artefact_path text,
  artefact_sha256 text,
  status text NOT NULL CHECK (status IN ('candidate', 'champion', 'shelved', 'retired')),
  created_at timestamptz NOT NULL,
  approved_by text
);

CREATE TABLE score.eval_run (
  eval_id text PRIMARY KEY,
  recipe text NOT NULL,
  model_semver text REFERENCES train.model_version (model_semver),
  dataset_id text NOT NULL REFERENCES train.dataset (dataset_id),
  folds integer NOT NULL,
  seed bigint NOT NULL,
  code_git_sha text,
  verdict text NOT NULL CHECK (verdict IN ('ACCEPT', 'HOLD', 'REJECT', 'NOT ACCEPTED')),
  scorecard_path text,
  created_at timestamptz NOT NULL
);

-- One row per scored armed day, fires included (the shadow log is the product while nothing is wired).
CREATE TABLE score.shadow_decision (
  eval_id text NOT NULL REFERENCES score.eval_run (eval_id) ON DELETE CASCADE,
  event_id text NOT NULL,
  asset text NOT NULL,
  role text NOT NULL,
  month text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('fire', 'skip')),
  reason_code text NOT NULL,
  pred_e double precision,
  p_loss double precision,
  detail text,
  y double precision,
  PRIMARY KEY (eval_id, event_id)
);

-- migrate:down
DROP TABLE score.shadow_decision;
DROP TABLE score.eval_run;
DROP TABLE train.model_version;
DROP TABLE train.dataset;
