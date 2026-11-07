"""INF-P2-T02 / T03 / T06: data quality.

reconcile(run_dir)  ledger vs journal for one run, event by event (the ledger is primary for money, the journal is
                    the fallback; both must agree on every trade fact)
run_checks()        SQL checks over the loaded runs -> ops.dq_result (pass / warn / fail per check and run)
cost_sources()      per asset: which cost components are measured and which are defaulted, and Leak from the DB
"""
import csv
import json
import os
from collections import Counter

from corb import contract, db
from corb.paths import RUNS, TOOLS, VAR

FACTS = [("side", None), ("day", None), ("entry_time", None), ("exit_time", None), ("exit_type", None),
         ("entry_requested", 1e-9), ("entry_price", 1e-9), ("exit_price", 1e-9), ("initial_stop", 1e-9),
         ("take_profit", 1e-9), ("volume", 1e-9), ("pnl_R", 1e-6), ("slip_entry_R", 1e-6), ("c_spread_R", 1e-4)]


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def reconcile(run_dir):
    """Journal events.csv vs the ledger converted to the journal format. Returns None when the run has no ledger."""
    journal = _read(os.path.join(run_dir, "events.csv"))
    led_evt = _read(os.path.join(run_dir, "ledger_events.csv"))
    if journal is None or led_evt is None:
        return None
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
        point = float(json.load(f)["point"])
    ledger, _ = contract.ledger_as_journal(_read(os.path.join(run_dir, "ledger_decisions.csv")), led_evt, point)
    j, lg = {e["event_id"]: e for e in journal}, {e["event_id"]: e for e in ledger}
    diffs, examples = Counter(), []
    for k in sorted(set(j) & set(lg)):
        for field, tol in FACTS:
            a, b = j[k][field], lg[k][field]
            same = a == b if tol is None else abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)))
            if not same:
                diffs[field] += 1
                if len(examples) < 5:
                    examples.append(f"{k} {field}: journal {a} vs ledger {b}")
    return dict(journal=len(j), ledger=len(lg), only_journal=len(set(j) - set(lg)),
                only_ledger=len(set(lg) - set(j)), field_diffs=dict(diffs), examples=examples)


def _q(sql):
    return [ln.split("\t") for ln in db.psql(sql).splitlines() if ln]


def _roles():
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    return {a["run_id"]: a.get("role", "asset") for a in assets.values()}


def run_checks():
    """Each check: one value per run, a status rule, and a detail. Production baselines are held to fail, the rest warn."""
    roles = _roles()
    runs = {k: (rid, kind, ledger == "t") for k, rid, kind, ledger in
            _q("SELECT run_key, run_id, kind, has_ledger FROM core.run;")}
    prod = {k for k, (rid, kind, _) in runs.items() if kind == "baseline" and roles.get(rid) == "asset"}
    results = []

    def add(check, key, value, bad, warn_only=False, detail="", never_fail=False):
        status = "pass" if not bad else ("warn" if never_fail or (warn_only and key not in prod) else "fail")
        results.append((check, key, status, value, detail))

    for key, n in _q("SELECT r.run_key, count(l.*) FILTER (WHERE l.place_time > l.entry_time) FROM core.run r "
                     "LEFT JOIN core.leg l USING (run_key) GROUP BY 1;"):
        add("dq.place_before_entry", key, int(n), int(n) > 0)
    for key, n in _q("SELECT r.run_key, count(e.*) FILTER (WHERE e.calendar_leak) FROM core.run r "
                     "LEFT JOIN core.event e USING (run_key) GROUP BY 1;"):
        add("dq.calendar_leak", key, int(n), int(n) > 0, warn_only=True, detail="CO-17: failed exit or overnight hold")
    for key, n in _q("SELECT r.run_key, count(e.*) FILTER (WHERE d.event_id IS NULL OR d.decision <> 'ARMED') "
                     "FROM core.run r LEFT JOIN core.event e USING (run_key) "
                     "LEFT JOIN core.decision d USING (run_key, event_id) GROUP BY 1;"):
        add("dq.event_without_armed_decision", key, int(n), int(n) > 0)
    for key, n in _q("SELECT r.run_key, count(e.*) FILTER (WHERE e.risk_ccy IS NULL) FROM core.run r "
                     "LEFT JOIN core.event e USING (run_key) WHERE r.has_ledger GROUP BY 1;"):
        add("dq.ledger_money_present", key, int(n), int(n) > 0)
    reasons = ("atr_band_low", "atr_band_high", "vol_floor", "cost_cap", "last_day", "warmup", "missing_bars",
               "skip_date", "other")
    rows = _q(f"""SELECT f.run_key, sum(abs(f.value - coalesce(d.n, 0)))
                  FROM core.funnel f
                  LEFT JOIN (SELECT run_key, reason, count(*) n FROM core.decision WHERE decision = 'SKIP'
                             GROUP BY 1, 2) d ON d.run_key = f.run_key AND 'skip_' || d.reason = f.counter
                  WHERE f.counter IN ({", ".join(f"'skip_{r}'" for r in reasons)}) GROUP BY 1;""")
    for key, n in rows:
        add("dq.funnel_matches_decisions", key, float(n), float(n) > 0)
    for key, armed, lot_min in _q("SELECT run_key, coalesce(sides_armed, 0), coalesce(sides_lot_min, 0) FROM core.run;"):
        share = int(lot_min) / int(armed) if int(armed) else 0.0
        add("dq.lot_min_share", key, share, share > 0.10, warn_only=True, detail="CO-08 L6 sizing leak > 10 %")
    for key, n in _q("SELECT r.run_key, count(d.*) FILTER (WHERE d.reason = 'warmup') FROM core.run r "
                     "LEFT JOIN core.decision d USING (run_key) GROUP BY 1;"):
        add("dq.warmup_days", key, int(n), int(n) > 10, never_fail=True,
            detail="N4: indicator warm-up; start the window earlier where broker history allows")
    for key, n in _q("SELECT r.run_key, count(l.*) FILTER (WHERE l.cost_flags LIKE '%swap=defaulted_zero%') "
                     "FROM core.run r LEFT JOIN core.leg l USING (run_key) GROUP BY 1;"):
        add("dq.swap_defaulted_overnight", key, int(n), int(n) > 0, warn_only=True,
            detail="overnight leg without a ledger: swap unknown")

    by_id = {rid: k for k, (rid, _, _) in runs.items()}
    for run_id in sorted(os.listdir(RUNS)):
        rec = reconcile(os.path.join(RUNS, run_id))
        key = by_id.get(run_id)
        if rec is None or key is None:
            continue
        n = rec["only_journal"] + rec["only_ledger"] + sum(rec["field_diffs"].values())
        add("dq.ledger_vs_journal", key, n, n > 0, detail=json.dumps(rec))

    os.makedirs(os.path.join(VAR, "stage"), exist_ok=True)
    with open(os.path.join(VAR, "stage", "dq_result.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["check_id", "run_key", "status", "value", "detail"])
        w.writerows(results)
    db.psql("BEGIN;\nDELETE FROM ops.dq_result;\n"
            "CREATE TEMP TABLE dq (check_id text, run_key text, status text, value float8, detail text);\n"
            "\\copy dq FROM '/corb/var/stage/dq_result.csv' WITH (FORMAT csv, HEADER true)\n"
            "INSERT INTO ops.dq_result SELECT check_id, run_key, status, value, detail, now() FROM dq;\nCOMMIT;\n")
    summary = Counter((c, s) for c, _, s, _, _ in results)
    failures = [dict(check=c, run=runs[k][0], value=v, detail=d[:300]) for c, k, s, v, d in results if s == "fail"]
    return summary, failures


def cost_sources():
    """Per asset run (baselines): share of legs whose money comes from the ledger, swap source counts, and Leak
    from SQL vs the frozen baseline (edge_framework.md §5.2 / aos_baseline.json)."""
    with open(os.path.join(TOOLS, "aos_baseline.json"), encoding="utf-8") as f:
        frozen = json.load(f)["assets"]
    out = {}
    for asset, fz in frozen.items():
        row = _q(f"""SELECT count(*), count(*) FILTER (WHERE l.cost_flags LIKE '%money=ledger%'),
                            count(*) FILTER (WHERE l.cost_flags LIKE '%swap=measured%'),
                            count(*) FILTER (WHERE l.cost_flags LIKE '%swap=defaulted%'), h.leak
                     FROM core.leg l JOIN core.run r USING (run_key) JOIN core.v_health h USING (run_key)
                     WHERE r.run_id = '{fz['run_id']}' GROUP BY h.leak;""")
        if not row:
            continue
        n, led, measured, defaulted, leak = row[0]
        out[asset] = dict(run_id=fz["run_id"], legs=int(n), money_from_ledger=int(led) / int(n),
                          swap_measured=int(measured), swap_defaulted=int(defaulted),
                          leak_db=float(leak), leak_frozen=fz["Leak"], leak_match=abs(float(leak) - fz["Leak"]) <= 0.001)
    return out
