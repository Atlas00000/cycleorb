-- INF-P1-T04: rebuild each event's R from its legs, and the per-run health core (unified_edge_framework.md §3-§4,
-- edge_framework.md §3). Zero-R events are excluded from WR and payoff (generic §1.3 rule 5).

-- migrate:up
CREATE VIEW core.v_event_r AS
SELECT e.run_key,
       e.event_id,
       e."pnl_R"                                                       AS pnl_r_contract,
       SUM(CASE l.direction WHEN 'long' THEN 1 ELSE -1 END
           * (l.exit_price - l.entry_price)) / e.risk_px              AS pnl_r_rebuilt,
       COUNT(*)                                                        AS legs
FROM core.event e
JOIN core.leg l USING (run_key, event_id)
GROUP BY e.run_key, e.event_id, e."pnl_R", e.risk_px;

CREATE VIEW core.v_health AS
WITH agg AS (
  SELECT run_key,
         COUNT(*)                                                      AS n,
         COUNT(*) FILTER (WHERE "pnl_R" > 0)                           AS wins,
         COUNT(*) FILTER (WHERE "pnl_R" < 0)                           AS losses,
         AVG("pnl_R") FILTER (WHERE "pnl_R" > 0)                       AS aw,
         -AVG("pnl_R") FILTER (WHERE "pnl_R" < 0)                      AS al,
         AVG("pnl_R")                                                  AS e,
         AVG("c_slip_prior_R")                                         AS c_slip
  FROM core.event
  GROUP BY run_key
), core_v AS (
  SELECT *, wins::float8 / NULLIF(wins + losses, 0) AS wr, aw / NULLIF(al, 0) AS r_payoff FROM agg
)
SELECT r.run_id, c.run_key, c.n, c.wins, c.losses, c.wr, c.aw, c.al, c.r_payoff, c.e,
       1 / (1 + c.r_payoff)                                            AS bwr,
       c.wr - 1 / (1 + c.r_payoff)                                     AS bm,
       c.wr * (c.r_payoff + 1) - 1                                     AS e_n,
       c.c_slip / (c.r_payoff + 1)                                     AS leak,
       c.wr - 1 / (1 + c.r_payoff) - c.c_slip / (c.r_payoff + 1)       AS ef
FROM core_v c
JOIN core.run r USING (run_key);

-- migrate:down
DROP VIEW core.v_health;
DROP VIEW core.v_event_r;
