-- INF-P3-T03: contract 1.2.0 — EA and offline values of the same feature live side by side (source in the key).

-- migrate:up
ALTER TABLE features.feature_value DROP CONSTRAINT feature_value_pkey;
ALTER TABLE features.feature_value ADD PRIMARY KEY (run_key, event_id, feature, source);

-- migrate:down
DELETE FROM features.feature_value WHERE source = 'offline';
ALTER TABLE features.feature_value DROP CONSTRAINT feature_value_pkey;
ALTER TABLE features.feature_value ADD PRIMARY KEY (run_key, event_id, feature);
