--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: core; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA core;


--
-- Name: features; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA features;


--
-- Name: ops; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ops;


--
-- Name: raw; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA raw;


--
-- Name: score; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA score;


--
-- Name: train; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA train;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: decision; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.decision (
    run_key text NOT NULL,
    event_id text NOT NULL,
    local_day date NOT NULL,
    setup text NOT NULL,
    magic bigint NOT NULL,
    decision text NOT NULL,
    reason text,
    atr_pct double precision,
    spread_pt double precision,
    cost_pct double precision,
    range_pt double precision,
    risk_money double precision,
    trend bigint,
    sides_placed bigint,
    sides_lot_min bigint,
    CONSTRAINT decision_decision_check CHECK ((decision = ANY (ARRAY['ARMED'::text, 'SKIP'::text]))),
    CONSTRAINT decision_event_id_check CHECK ((event_id ~ '^[0-9]+-[0-9]{8}$'::text)),
    CONSTRAINT decision_reason_check CHECK ((reason = ANY (ARRAY['atr_band_low'::text, 'atr_band_high'::text, 'vol_floor'::text, 'cost_cap'::text, 'last_day'::text, 'warmup'::text, 'missing_bars'::text, 'price_through'::text, 'already_traded'::text, 'skip_date'::text, 'other'::text, 'guard'::text]))),
    CONSTRAINT decision_setup_check CHECK ((setup = ANY (ARRAY['LON'::text, 'NY'::text, 'TKY'::text]))),
    CONSTRAINT decision_sides_lot_min_check CHECK (((sides_lot_min >= 0) AND (sides_lot_min <= 2))),
    CONSTRAINT decision_sides_placed_check CHECK (((sides_placed >= 0) AND (sides_placed <= 2))),
    CONSTRAINT decision_trend_check CHECK ((trend = ANY (ARRAY[('-1'::integer)::bigint, (0)::bigint, (1)::bigint])))
);


--
-- Name: event; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.event (
    run_key text NOT NULL,
    event_id text NOT NULL,
    signal_tag text NOT NULL,
    magic bigint NOT NULL,
    local_day date NOT NULL,
    n_legs bigint NOT NULL,
    risk_px double precision NOT NULL,
    risk_ccy double precision,
    equity_at_open double precision,
    risk_pct double precision,
    "pnl_R" double precision NOT NULL,
    exit_type text NOT NULL,
    close_reason text,
    "c_spread_R" double precision,
    "c_slip_prior_R" double precision,
    "slip_entry_R" double precision,
    hold_min double precision,
    atr_pct double precision,
    trend bigint,
    calendar_leak boolean NOT NULL,
    CONSTRAINT event_event_id_check CHECK ((event_id ~ '^[0-9]+-[0-9]{8}$'::text)),
    CONSTRAINT event_exit_type_check CHECK ((exit_type = ANY (ARRAY['SL'::text, 'TP'::text, 'TIME'::text]))),
    CONSTRAINT event_n_legs_check CHECK (((n_legs >= 1) AND (n_legs <= 2))),
    CONSTRAINT event_risk_px_check CHECK ((risk_px > (0)::double precision)),
    CONSTRAINT event_signal_tag_check CHECK ((signal_tag = ANY (ARRAY['LON'::text, 'NY'::text, 'TKY'::text]))),
    CONSTRAINT event_trend_check CHECK ((trend = ANY (ARRAY[('-1'::integer)::bigint, (0)::bigint, (1)::bigint])))
);


--
-- Name: funnel; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.funnel (
    run_key text NOT NULL,
    counter text NOT NULL,
    value bigint NOT NULL,
    CONSTRAINT funnel_value_check CHECK ((value >= 0))
);


--
-- Name: leg; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.leg (
    run_key text NOT NULL,
    leg_id text NOT NULL,
    event_id text NOT NULL,
    symbol text NOT NULL,
    direction text NOT NULL,
    place_time timestamp with time zone,
    entry_time timestamp with time zone NOT NULL,
    entry_price double precision NOT NULL,
    entry_requested double precision,
    exit_time timestamp with time zone NOT NULL,
    exit_price double precision NOT NULL,
    exit_requested double precision,
    initial_stop double precision NOT NULL,
    take_profit double precision,
    volume double precision NOT NULL,
    pnl_gross_ccy double precision,
    cost_spread_ccy double precision,
    cost_commission_ccy double precision,
    cost_swap_ccy double precision,
    cost_slippage_ccy double precision,
    pnl_net_ccy double precision,
    cost_flags text NOT NULL,
    CONSTRAINT leg_check CHECK ((exit_time >= entry_time)),
    CONSTRAINT leg_direction_check CHECK ((direction = ANY (ARRAY['long'::text, 'short'::text]))),
    CONSTRAINT leg_volume_check CHECK ((volume > (0)::double precision))
);


--
-- Name: run; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.run (
    run_key text NOT NULL,
    run_id text NOT NULL,
    ea_name text NOT NULL,
    ea_version text NOT NULL,
    symbol text NOT NULL,
    magic_base bigint NOT NULL,
    setups text NOT NULL,
    window_from date NOT NULL,
    window_to date NOT NULL,
    deposit double precision NOT NULL,
    final_balance double precision,
    run_tag text,
    kind text NOT NULL,
    designed_rr double precision NOT NULL,
    risk_definition text NOT NULL,
    regime_filtered boolean NOT NULL,
    baseline_frequency double precision,
    costs_defaulted text NOT NULL,
    server_utc_offset_h bigint NOT NULL,
    preset_sha256 text NOT NULL,
    events_sha256 text NOT NULL,
    journal_sha16 text,
    n_events bigint NOT NULL,
    armed_days bigint,
    sides_armed bigint,
    sides_lot_min bigint,
    has_ledger boolean NOT NULL,
    CONSTRAINT run_deposit_check CHECK ((deposit >= (0)::double precision)),
    CONSTRAINT run_designed_rr_check CHECK ((designed_rr >= (1)::double precision)),
    CONSTRAINT run_ea_name_check CHECK ((ea_name = 'CycleORB'::text)),
    CONSTRAINT run_kind_check CHECK ((kind = ANY (ARRAY['baseline'::text, 'variant'::text, 'reference'::text, 'live'::text]))),
    CONSTRAINT run_n_events_check CHECK ((n_events >= 0)),
    CONSTRAINT run_risk_definition_check CHECK ((risk_definition = 'hard_stop'::text)),
    CONSTRAINT run_run_key_check CHECK ((run_key ~ '^[0-9a-f]{16}$'::text))
);


--
-- Name: shadow; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.shadow (
    run_key text NOT NULL,
    event_id text NOT NULL,
    setup text NOT NULL,
    arm_buy boolean,
    arm_sell boolean,
    withheld_buy text,
    withheld_sell text,
    status text NOT NULL,
    side text,
    fill_time timestamp with time zone,
    fill_price double precision,
    exit_time timestamp with time zone,
    exit_price double precision,
    exit_type text,
    "shadow_R" double precision,
    CONSTRAINT shadow_exit_type_check CHECK ((exit_type = ANY (ARRAY['SL'::text, 'TP'::text, 'TIME'::text]))),
    CONSTRAINT shadow_setup_check CHECK ((setup = ANY (ARRAY['LON'::text, 'NY'::text, 'TKY'::text]))),
    CONSTRAINT shadow_status_check CHECK ((status = ANY (ARRAY['FILLED'::text, 'NO_FILL'::text])))
);


--
-- Name: v_event_r; Type: VIEW; Schema: core; Owner: -
--

CREATE VIEW core.v_event_r AS
 SELECT e.run_key,
    e.event_id,
    e."pnl_R" AS pnl_r_contract,
    (sum(((
        CASE l.direction
            WHEN 'long'::text THEN 1
            ELSE '-1'::integer
        END)::double precision * (l.exit_price - l.entry_price))) / e.risk_px) AS pnl_r_rebuilt,
    count(*) AS legs
   FROM (core.event e
     JOIN core.leg l USING (run_key, event_id))
  GROUP BY e.run_key, e.event_id, e."pnl_R", e.risk_px;


--
-- Name: v_health; Type: VIEW; Schema: core; Owner: -
--

CREATE VIEW core.v_health AS
 WITH agg AS (
         SELECT event.run_key,
            count(*) AS n,
            count(*) FILTER (WHERE (event."pnl_R" > (0)::double precision)) AS wins,
            count(*) FILTER (WHERE (event."pnl_R" < (0)::double precision)) AS losses,
            avg(event."pnl_R") FILTER (WHERE (event."pnl_R" > (0)::double precision)) AS aw,
            (- avg(event."pnl_R") FILTER (WHERE (event."pnl_R" < (0)::double precision))) AS al,
            avg(event."pnl_R") AS e,
            avg(event."c_slip_prior_R") AS c_slip
           FROM core.event
          GROUP BY event.run_key
        ), core_v AS (
         SELECT agg.run_key,
            agg.n,
            agg.wins,
            agg.losses,
            agg.aw,
            agg.al,
            agg.e,
            agg.c_slip,
            ((agg.wins)::double precision / (NULLIF((agg.wins + agg.losses), 0))::double precision) AS wr,
            (agg.aw / NULLIF(agg.al, (0)::double precision)) AS r_payoff
           FROM agg
        )
 SELECT r.run_id,
    c.run_key,
    c.n,
    c.wins,
    c.losses,
    c.wr,
    c.aw,
    c.al,
    c.r_payoff,
    c.e,
    ((1)::double precision / ((1)::double precision + c.r_payoff)) AS bwr,
    (c.wr - ((1)::double precision / ((1)::double precision + c.r_payoff))) AS bm,
    ((c.wr * (c.r_payoff + (1)::double precision)) - (1)::double precision) AS e_n,
    (c.c_slip / (c.r_payoff + (1)::double precision)) AS leak,
    ((c.wr - ((1)::double precision / ((1)::double precision + c.r_payoff))) - (c.c_slip / (c.r_payoff + (1)::double precision))) AS ef
   FROM (core_v c
     JOIN core.run r USING (run_key));


--
-- Name: bar_index; Type: TABLE; Schema: features; Owner: -
--

CREATE TABLE features.bar_index (
    symbol text NOT NULL,
    tf text NOT NULL,
    year integer NOT NULL,
    rows integer NOT NULL,
    first_bar timestamp with time zone NOT NULL,
    last_bar timestamp with time zone NOT NULL,
    lake_path text NOT NULL,
    sha256 text NOT NULL,
    source text NOT NULL,
    exported_at timestamp with time zone NOT NULL,
    CONSTRAINT bar_index_rows_check CHECK ((rows >= 0)),
    CONSTRAINT bar_index_tf_check CHECK ((tf = ANY (ARRAY['M1'::text, 'M5'::text, 'H1'::text, 'D1'::text])))
);


--
-- Name: calendar_snapshot; Type: TABLE; Schema: features; Owner: -
--

CREATE TABLE features.calendar_snapshot (
    snapshot_sha256 text NOT NULL,
    events integer NOT NULL,
    first_event timestamp with time zone,
    last_event timestamp with time zone,
    taken_at timestamp with time zone NOT NULL
);


--
-- Name: feature_def; Type: TABLE; Schema: features; Owner: -
--

CREATE TABLE features.feature_def (
    feature text NOT NULL,
    version integer NOT NULL,
    dtype text NOT NULL,
    unit text,
    as_of text NOT NULL,
    offline boolean NOT NULL,
    definition text NOT NULL,
    CONSTRAINT feature_def_dtype_check CHECK ((dtype = ANY (ARRAY['number'::text, 'integer'::text, 'boolean'::text, 'string'::text])))
);


--
-- Name: feature_value; Type: TABLE; Schema: features; Owner: -
--

CREATE TABLE features.feature_value (
    run_key text NOT NULL,
    event_id text NOT NULL,
    feature text NOT NULL,
    value_num double precision,
    value_text text,
    as_of_ts timestamp with time zone NOT NULL,
    decision_ts timestamp with time zone NOT NULL,
    source text NOT NULL,
    CONSTRAINT feature_value_check CHECK ((as_of_ts <= decision_ts)),
    CONSTRAINT feature_value_source_check CHECK ((source = ANY (ARRAY['ea'::text, 'offline'::text])))
);


--
-- Name: regime_tape; Type: TABLE; Schema: features; Owner: -
--

CREATE TABLE features.regime_tape (
    asset text NOT NULL,
    local_day date NOT NULL,
    setup text NOT NULL,
    tagger_version integer NOT NULL,
    source_run_key text NOT NULL,
    feature_run_key text,
    decision text NOT NULL,
    reason text,
    range_atr_pct double precision,
    range_atr_tercile text,
    vol_pct double precision,
    vol_tercile text,
    trend_side integer,
    er50 double precision,
    ev_tier1_entry integer,
    ev_tier1_hold integer,
    opex boolean,
    quad_witching boolean,
    us_open_in_hold boolean,
    CONSTRAINT regime_tape_decision_check CHECK ((decision = ANY (ARRAY['ARMED'::text, 'SKIP'::text]))),
    CONSTRAINT regime_tape_range_atr_tercile_check CHECK ((range_atr_tercile = ANY (ARRAY['narrow'::text, 'mid'::text, 'wide'::text]))),
    CONSTRAINT regime_tape_setup_check CHECK ((setup = ANY (ARRAY['LON'::text, 'NY'::text, 'TKY'::text]))),
    CONSTRAINT regime_tape_trend_side_check CHECK ((trend_side = ANY (ARRAY['-1'::integer, 0, 1]))),
    CONSTRAINT regime_tape_vol_tercile_check CHECK ((vol_tercile = ANY (ARRAY['low'::text, 'mid'::text, 'high'::text])))
);


--
-- Name: dq_result; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.dq_result (
    check_id text NOT NULL,
    run_key text NOT NULL,
    status text NOT NULL,
    value double precision,
    detail text,
    checked_at timestamp with time zone NOT NULL,
    CONSTRAINT dq_result_status_check CHECK ((status = ANY (ARRAY['pass'::text, 'warn'::text, 'fail'::text])))
);


--
-- Name: ingest_state; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.ingest_state (
    run_key text NOT NULL,
    content_sha256 text NOT NULL,
    ingested_at timestamp with time zone NOT NULL
);


--
-- Name: job; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.job (
    job_id bigint NOT NULL,
    command text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    enqueued_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    worker text,
    exit_code integer,
    log_path text,
    CONSTRAINT job_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'done'::text, 'failed'::text])))
);


--
-- Name: job_job_id_seq; Type: SEQUENCE; Schema: ops; Owner: -
--

CREATE SEQUENCE ops.job_job_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_job_id_seq; Type: SEQUENCE OWNED BY; Schema: ops; Owner: -
--

ALTER SEQUENCE ops.job_job_id_seq OWNED BY ops.job.job_id;


--
-- Name: metric; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.metric (
    ts timestamp with time zone NOT NULL,
    name text NOT NULL,
    subject text NOT NULL,
    value double precision,
    status text,
    detail text,
    CONSTRAINT metric_status_check CHECK ((status = ANY (ARRAY['ok'::text, 'warn'::text, 'alarm'::text])))
);


--
-- Name: reason_code; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.reason_code (
    code text NOT NULL,
    layer text NOT NULL,
    verdict text NOT NULL,
    meaning text NOT NULL,
    CONSTRAINT reason_code_verdict_check CHECK ((verdict = ANY (ARRAY['fire'::text, 'skip'::text, 'block'::text])))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: journal_line; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.journal_line (
    file_sha256 text NOT NULL,
    line_no integer NOT NULL,
    run_seq integer,
    symbol text,
    ea_version text,
    sim_time timestamp without time zone,
    event_id text,
    kind text,
    message text NOT NULL
);


--
-- Name: source_file; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.source_file (
    file_sha256 text NOT NULL,
    origin text NOT NULL,
    kind text NOT NULL,
    src_path text NOT NULL,
    landed_path text NOT NULL,
    bytes bigint NOT NULL,
    landed_at timestamp with time zone NOT NULL,
    source_commit text,
    CONSTRAINT source_file_bytes_check CHECK ((bytes >= 0)),
    CONSTRAINT source_file_file_sha256_check CHECK ((file_sha256 ~ '^[0-9a-f]{64}$'::text))
);


--
-- Name: cell_bm; Type: TABLE; Schema: score; Owner: -
--

CREATE TABLE score.cell_bm (
    dataset text NOT NULL,
    asset text NOT NULL,
    dim text NOT NULL,
    value text NOT NULL,
    stream text NOT NULL,
    n integer NOT NULL,
    wr double precision,
    r_payoff double precision,
    bm double precision,
    mean_r double precision,
    m double precision,
    qualifying boolean NOT NULL,
    bm_nonpos boolean,
    computed_at timestamp with time zone NOT NULL,
    CONSTRAINT cell_bm_stream_check CHECK ((stream = ANY (ARRAY['actual'::text, 'shadow'::text])))
);


--
-- Name: eval_run; Type: TABLE; Schema: score; Owner: -
--

CREATE TABLE score.eval_run (
    eval_id text NOT NULL,
    recipe text NOT NULL,
    model_semver text,
    dataset_id text NOT NULL,
    folds integer NOT NULL,
    seed bigint NOT NULL,
    code_git_sha text,
    verdict text NOT NULL,
    scorecard_path text,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT eval_run_verdict_check CHECK ((verdict = ANY (ARRAY['ACCEPT'::text, 'HOLD'::text, 'REJECT'::text, 'NOT ACCEPTED'::text])))
);


--
-- Name: shadow_decision; Type: TABLE; Schema: score; Owner: -
--

CREATE TABLE score.shadow_decision (
    eval_id text NOT NULL,
    event_id text NOT NULL,
    asset text NOT NULL,
    role text NOT NULL,
    month text NOT NULL,
    verdict text NOT NULL,
    reason_code text NOT NULL,
    pred_e double precision,
    p_loss double precision,
    detail text,
    y double precision,
    CONSTRAINT shadow_decision_verdict_check CHECK ((verdict = ANY (ARRAY['fire'::text, 'skip'::text])))
);


--
-- Name: dataset; Type: TABLE; Schema: train; Owner: -
--

CREATE TABLE train.dataset (
    dataset_id text NOT NULL,
    source text NOT NULL,
    rows integer NOT NULL,
    label text NOT NULL,
    window_from date,
    window_to date,
    sha256 text NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: model_version; Type: TABLE; Schema: train; Owner: -
--

CREATE TABLE train.model_version (
    model_semver text NOT NULL,
    family text NOT NULL,
    params jsonb NOT NULL,
    features jsonb NOT NULL,
    dataset_id text NOT NULL,
    policy_sha256 text NOT NULL,
    artefact_path text,
    artefact_sha256 text,
    status text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    approved_by text,
    CONSTRAINT model_version_status_check CHECK ((status = ANY (ARRAY['candidate'::text, 'champion'::text, 'shelved'::text, 'retired'::text])))
);


--
-- Name: job job_id; Type: DEFAULT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.job ALTER COLUMN job_id SET DEFAULT nextval('ops.job_job_id_seq'::regclass);


--
-- Name: decision decision_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.decision
    ADD CONSTRAINT decision_pkey PRIMARY KEY (run_key, event_id);


--
-- Name: event event_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.event
    ADD CONSTRAINT event_pkey PRIMARY KEY (run_key, event_id);


--
-- Name: funnel funnel_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.funnel
    ADD CONSTRAINT funnel_pkey PRIMARY KEY (run_key, counter);


--
-- Name: leg leg_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.leg
    ADD CONSTRAINT leg_pkey PRIMARY KEY (run_key, leg_id);


--
-- Name: run run_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.run
    ADD CONSTRAINT run_pkey PRIMARY KEY (run_key);


--
-- Name: shadow shadow_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.shadow
    ADD CONSTRAINT shadow_pkey PRIMARY KEY (run_key, event_id);


--
-- Name: bar_index bar_index_pkey; Type: CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.bar_index
    ADD CONSTRAINT bar_index_pkey PRIMARY KEY (symbol, tf, year, source);


--
-- Name: calendar_snapshot calendar_snapshot_pkey; Type: CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.calendar_snapshot
    ADD CONSTRAINT calendar_snapshot_pkey PRIMARY KEY (snapshot_sha256);


--
-- Name: feature_def feature_def_pkey; Type: CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.feature_def
    ADD CONSTRAINT feature_def_pkey PRIMARY KEY (feature, version);


--
-- Name: feature_value feature_value_pkey; Type: CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.feature_value
    ADD CONSTRAINT feature_value_pkey PRIMARY KEY (run_key, event_id, feature, source);


--
-- Name: regime_tape regime_tape_pkey; Type: CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.regime_tape
    ADD CONSTRAINT regime_tape_pkey PRIMARY KEY (asset, local_day, setup, tagger_version);


--
-- Name: dq_result dq_result_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.dq_result
    ADD CONSTRAINT dq_result_pkey PRIMARY KEY (check_id, run_key);


--
-- Name: ingest_state ingest_state_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.ingest_state
    ADD CONSTRAINT ingest_state_pkey PRIMARY KEY (run_key);


--
-- Name: job job_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.job
    ADD CONSTRAINT job_pkey PRIMARY KEY (job_id);


--
-- Name: metric metric_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.metric
    ADD CONSTRAINT metric_pkey PRIMARY KEY (ts, name, subject);


--
-- Name: reason_code reason_code_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.reason_code
    ADD CONSTRAINT reason_code_pkey PRIMARY KEY (code);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: journal_line journal_line_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw.journal_line
    ADD CONSTRAINT journal_line_pkey PRIMARY KEY (file_sha256, line_no);


--
-- Name: source_file source_file_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw.source_file
    ADD CONSTRAINT source_file_pkey PRIMARY KEY (file_sha256);


--
-- Name: cell_bm cell_bm_pkey; Type: CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.cell_bm
    ADD CONSTRAINT cell_bm_pkey PRIMARY KEY (dataset, asset, dim, value, stream);


--
-- Name: eval_run eval_run_pkey; Type: CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.eval_run
    ADD CONSTRAINT eval_run_pkey PRIMARY KEY (eval_id);


--
-- Name: shadow_decision shadow_decision_pkey; Type: CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.shadow_decision
    ADD CONSTRAINT shadow_decision_pkey PRIMARY KEY (eval_id, event_id);


--
-- Name: dataset dataset_pkey; Type: CONSTRAINT; Schema: train; Owner: -
--

ALTER TABLE ONLY train.dataset
    ADD CONSTRAINT dataset_pkey PRIMARY KEY (dataset_id);


--
-- Name: model_version model_version_pkey; Type: CONSTRAINT; Schema: train; Owner: -
--

ALTER TABLE ONLY train.model_version
    ADD CONSTRAINT model_version_pkey PRIMARY KEY (model_semver);


--
-- Name: job_queued; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX job_queued ON ops.job USING btree (status, job_id);


--
-- Name: metric_name_subject; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX metric_name_subject ON ops.metric USING btree (name, subject, ts DESC);


--
-- Name: journal_line_event; Type: INDEX; Schema: raw; Owner: -
--

CREATE INDEX journal_line_event ON raw.journal_line USING btree (event_id) WHERE (event_id IS NOT NULL);


--
-- Name: decision decision_run_key_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.decision
    ADD CONSTRAINT decision_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: event event_run_key_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.event
    ADD CONSTRAINT event_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: funnel funnel_run_key_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.funnel
    ADD CONSTRAINT funnel_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: leg leg_run_key_event_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.leg
    ADD CONSTRAINT leg_run_key_event_id_fkey FOREIGN KEY (run_key, event_id) REFERENCES core.event(run_key, event_id) ON DELETE CASCADE;


--
-- Name: shadow shadow_run_key_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.shadow
    ADD CONSTRAINT shadow_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: feature_value feature_value_run_key_fkey; Type: FK CONSTRAINT; Schema: features; Owner: -
--

ALTER TABLE ONLY features.feature_value
    ADD CONSTRAINT feature_value_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: ingest_state ingest_state_run_key_fkey; Type: FK CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.ingest_state
    ADD CONSTRAINT ingest_state_run_key_fkey FOREIGN KEY (run_key) REFERENCES core.run(run_key) ON DELETE CASCADE;


--
-- Name: eval_run eval_run_dataset_id_fkey; Type: FK CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.eval_run
    ADD CONSTRAINT eval_run_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES train.dataset(dataset_id);


--
-- Name: eval_run eval_run_model_semver_fkey; Type: FK CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.eval_run
    ADD CONSTRAINT eval_run_model_semver_fkey FOREIGN KEY (model_semver) REFERENCES train.model_version(model_semver);


--
-- Name: shadow_decision shadow_decision_eval_id_fkey; Type: FK CONSTRAINT; Schema: score; Owner: -
--

ALTER TABLE ONLY score.shadow_decision
    ADD CONSTRAINT shadow_decision_eval_id_fkey FOREIGN KEY (eval_id) REFERENCES score.eval_run(eval_id) ON DELETE CASCADE;


--
-- Name: model_version model_version_dataset_id_fkey; Type: FK CONSTRAINT; Schema: train; Owner: -
--

ALTER TABLE ONLY train.model_version
    ADD CONSTRAINT model_version_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES train.dataset(dataset_id);


--
-- PostgreSQL database dump complete
--
