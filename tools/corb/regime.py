"""INF-P3-T01 / T04 / T05 / T06: feature registry, point-in-time audit, regime tape, regime-cell BM.

registry()     infra/features.json -> features.feature_def; must name exactly the EA's feature columns
audit()        PIT checks on the stored EA features (no value after its decision, no decision after the fill,
               no label column in the features schema). The bar-based future-shift test needs INF-P3-T03
build_tape()   one row per evaluated setup-day per asset: range/ATR tercile (CO-09, the traded set's cut points,
               as corb_bench), vol tercile, D1 trend side, calendar tags, US cash open inside the hold.
               ER50 needs bars (INF-P3-T02) and stays null until then
build_cells()  BM per regime cell on the actual (baseline run) and shadow (P1obs run) streams -> score.cell_bm,
               checked against the frozen cells in tools/aos_baseline.json
"""
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import corb_metrics as cm

from corb import contract, db
from corb.paths import INFRA, RUNS, TOOLS, VAR

REGISTRY = os.path.join(INFRA, "features.json")
TAGGER_VERSION = 1
ZONES = {"LON": "Europe/London", "NY": "America/New_York", "TKY": "Asia/Tokyo"}
EXIT_INPUT = {"LON": "InpLonExit", "NY": "InpNYExit", "TKY": "InpTkyExit"}
STAGE = os.path.join(VAR, "stage")


def _q(sql):
    return [ln.split("\t") for ln in db.psql(sql).splitlines() if ln]


def _assets():
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        return json.load(f)["assets"]


def _run_key(run_id):
    rows = _q(f"SELECT run_key FROM core.run WHERE run_id = '{run_id}';")
    return rows[0][0] if rows else None


def _copy(table, rows, cols, delete_sql):
    os.makedirs(STAGE, exist_ok=True)
    path = os.path.join(STAGE, table.split(".")[1] + ".csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r.get(c) is None else ("true" if r[c] is True else "false" if r[c] is False else r[c])
                        for c in cols])
    db.psql(f"BEGIN;\n{delete_sql}\n\\copy {table} ({', '.join(cols)}) FROM '/corb/var/stage/{os.path.basename(path)}' "
            f"WITH (FORMAT csv, HEADER true)\nCOMMIT;\n")


# ---------------------------------------------------------------- T01
def registry():
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    names = [x["name"] for x in reg["features"]]
    rows = [dict(feature=x["name"], version=reg["version"], dtype=x["dtype"], unit=x["unit"], as_of=x["as_of"],
                 offline=x["offline"], definition=x["definition"]) for x in reg["features"]]
    _copy("features.feature_def", rows, ["feature", "version", "dtype", "unit", "as_of", "offline", "definition"],
          f"DELETE FROM features.feature_def WHERE version = {reg['version']};")
    with open(os.path.join(os.path.dirname(RUNS), "tape", "tape_P1obs.csv"), encoding="utf-8") as f:
        tape_cols = next(csv.reader(f))
    stored = {r[0] for r in _q("SELECT DISTINCT feature FROM features.feature_value;")}
    return dict(version=reg["version"], features=len(names), offline=sum(x["offline"] for x in reg["features"]),
                not_in_adapter=sorted(set(names) - set(contract.FEATURES)),
                adapter_not_registered=sorted(set(contract.FEATURES) - set(names)),
                tape_features_not_registered=sorted(set(tape_cols) & set(contract.FEATURES) - set(names)),
                stored_not_registered=sorted(stored - set(names)))


# ---------------------------------------------------------------- T04
def audit():
    after_decision = int(_q("SELECT count(*) FROM features.feature_value WHERE as_of_ts > decision_ts;")[0][0])
    after_fill = int(_q("""SELECT count(*) FROM (SELECT DISTINCT f.run_key, f.event_id, f.decision_ts
                           FROM features.feature_value f JOIN core.leg l USING (run_key, event_id)
                           WHERE f.decision_ts > l.entry_time) x;""")[0][0])
    label_cols = [r[0] for r in _q("""SELECT table_name || '.' || column_name FROM information_schema.columns
                    WHERE table_schema = 'features' AND (column_name ILIKE '%pnl%' OR column_name ILIKE '%shadow%'
                    OR column_name ILIKE 'exit%' OR column_name ILIKE '%_r');""")]
    checked = int(_q("SELECT count(*) FROM features.feature_value;")[0][0])
    return dict(values_checked=checked, as_of_after_decision=after_decision, decided_after_fill=after_fill,
                label_columns_in_features=label_cols, future_shift_test="pending INF-P3-T03 (needs bars)")


# ---------------------------------------------------------------- T05
def _band(a, q1, q2):
    return None if a is None else ("narrow" if a < q1 else ("mid" if a < q2 else "wide"))


def _vol_tercile(v):
    return None if v is None else ("low" if v < 100 / 3 else ("mid" if v < 200 / 3 else "high"))


def _num(s):
    return None if s in (None, "") else float(s)


def _utc(day, hhmm, zone):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), ZoneInfo(zone)).astimezone(timezone.utc)


def build_tape():
    rows, summary = [], {}
    feats_wanted = ("vol_pct", "trend_side", "ev_tier1_entry", "ev_tier1_hold", "opex", "quad_witching")
    for asset, a in _assets().items():
        base, feat = _run_key(a["run_id"]), _run_key(a["run_id"] + "_P1obs")
        if base is None:
            continue
        with open(os.path.join(RUNS, a["run_id"], "meta.json"), encoding="utf-8") as f:
            inputs = json.load(f)["inputs"]
        atrs = sorted(float(r[0]) for r in _q(f"SELECT atr_pct FROM core.event WHERE run_key = '{base}' "
                                               f"AND atr_pct IS NOT NULL;"))
        q1, q2 = atrs[len(atrs) // 3], atrs[2 * len(atrs) // 3]
        fv = defaultdict(dict)
        if feat:
            for eid, name, num, text, as_of in _q(
                    f"SELECT event_id, feature, value_num, value_text, as_of_ts FROM features.feature_value "
                    f"WHERE run_key = '{feat}' AND feature IN ({', '.join(repr(x) for x in feats_wanted)});"):
                fv[eid][name] = _num(num) if num else text
                fv[eid]["_as_of"] = as_of
        n = 0
        for eid, day, setup, decision, reason, atr in _q(
                f"SELECT event_id, local_day, setup, decision, coalesce(reason, ''), atr_pct FROM core.decision "
                f"WHERE run_key = '{base}';"):
            f = fv.get(eid, {})
            d = datetime.strptime(day, "%Y-%m-%d").date()
            us_open = None
            if "_as_of" in f and inputs.get(EXIT_INPUT[setup]):
                range_end = datetime.fromisoformat(f["_as_of"].replace(" ", "T")).astimezone(timezone.utc)
                exit_utc = _utc(d, inputs[EXIT_INPUT[setup]], ZONES[setup])
                us_open = range_end < _utc(d, "09:30", ZONES["NY"]) <= exit_utc
            ts = f.get("trend_side")
            rows.append(dict(asset=asset, local_day=day, setup=setup, tagger_version=TAGGER_VERSION,
                             source_run_key=base, feature_run_key=feat, decision=decision, reason=reason or None,
                             range_atr_pct=_num(atr), range_atr_tercile=_band(_num(atr), q1, q2),
                             vol_pct=f.get("vol_pct"), vol_tercile=_vol_tercile(f.get("vol_pct")),
                             trend_side=None if ts is None else int(ts), er50=None,
                             ev_tier1_entry=None if f.get("ev_tier1_entry") is None else int(f["ev_tier1_entry"]),
                             ev_tier1_hold=None if f.get("ev_tier1_hold") is None else int(f["ev_tier1_hold"]),
                             opex=None if f.get("opex") is None else f["opex"] == 1.0,
                             quad_witching=None if f.get("quad_witching") is None else f["quad_witching"] == 1.0,
                             us_open_in_hold=us_open))
            n += 1
        summary[asset] = dict(days=n, with_features=sum(1 for r in rows[-n:] if r["vol_pct"] is not None or
                                                         r["trend_side"] is not None), cuts=[q1, q2])
    cols = ["asset", "local_day", "setup", "tagger_version", "source_run_key", "feature_run_key", "decision", "reason",
            "range_atr_pct", "range_atr_tercile", "vol_pct", "vol_tercile", "trend_side", "er50", "ev_tier1_entry",
            "ev_tier1_hold", "opex", "quad_witching", "us_open_in_hold"]
    _copy("features.regime_tape", rows, cols, f"DELETE FROM features.regime_tape WHERE tagger_version = {TAGGER_VERSION};")
    return summary


# ---------------------------------------------------------------- T06
def _cell(rs):
    c = cm.core(rs)
    m = cm.wilson_half(c["WR"], c["n"]) if c["n"] and c["BM"] is not None else None
    q = c["n"] >= 15 and c["BM"] is not None
    return dict(n=c["n"], wr=c["WR"], r_payoff=c["R"], bm=c["BM"], mean_r=c["E"], m=m, qualifying=q,
                bm_nonpos=(c["BM"] <= 0) if q else None)


def build_cells(dataset="baseline-v1.11"):
    with open(os.path.join(TOOLS, "aos_baseline.json"), encoding="utf-8") as f:
        frozen = json.load(f)["assets"]
    tape = defaultdict(dict)
    for asset, day, setup, rng, vol, trend, ev_hold in _q(
            f"SELECT asset, local_day, setup, range_atr_tercile, vol_tercile, trend_side, ev_tier1_hold "
            f"FROM features.regime_tape WHERE tagger_version = {TAGGER_VERSION};"):
        tape[asset][(day, setup)] = dict(range_atr=rng or None, vol=vol or None, trend=_num(trend),
                                         ev_hold=None if ev_hold == "" else int(ev_hold) > 0)

    def tags(t, side):
        sign = 1 if side in ("buy", "long") else -1
        align = None if t.get("trend") is None else ("flat" if t["trend"] == 0 else
                                                      ("with" if t["trend"] == sign else "against"))
        return dict(range_atr=t.get("range_atr"), side="buy" if sign > 0 else "sell", vol_tercile=t.get("vol"),
                    trend_align=align, event_in_hold=None if t.get("ev_hold") is None else
                    ("yes" if t["ev_hold"] else "no"))

    rows, checks, flagged = [], [], []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for asset, a in _assets().items():
        base, feat = _run_key(a["run_id"]), _run_key(a["run_id"] + "_P1obs")
        streams = {"actual": _q(f"""SELECT e.local_day, e.signal_tag, l.direction, e."pnl_R" FROM core.event e
                                    JOIN core.leg l USING (run_key, event_id) WHERE e.run_key = '{base}';""")}
        if feat:
            streams["shadow"] = _q(f"""SELECT d.local_day, s.setup, s.side, s."shadow_R" FROM core.shadow s
                                       JOIN core.decision d USING (run_key, event_id)
                                       WHERE s.run_key = '{feat}' AND s.status = 'FILLED';""")
        cells = {}
        for stream, evs in streams.items():
            groups = defaultdict(list)
            for day, setup, side, r in evs:
                for dim, val in tags(tape[asset].get((day, setup), {}), side).items():
                    if val is not None:
                        groups[(dim, val)].append(float(r))
            for (dim, val), rs in sorted(groups.items()):
                c = _cell(rs)
                cells[(stream, dim, val)] = c
                rows.append(dict(dataset=dataset, asset=asset, dim=dim, value=val, stream=stream, computed_at=now, **c))
        for (dim, val, key) in [("range_atr", b, f"range_atr_{b}") for b in ("narrow", "mid", "wide")] + \
                               [("side", s, f"side_{s}") for s in ("buy", "sell")]:
            fz, got = frozen[asset]["cells"].get(key), cells.get(("actual", dim, val))
            if fz is None:
                continue
            checks.append(dict(name=f"{asset}.{key}.n", ok=got is not None and got["n"] == fz["n"],
                               expected=fz["n"], got=got and got["n"]))
            if fz["BM"] is not None:
                checks.append(dict(name=f"{asset}.{key}.BM", ok=got is not None and got["bm"] is not None
                                   and abs(got["bm"] - fz["BM"]) <= 0.001, expected=fz["BM"], got=got and got["bm"]))
        for (stream, dim, val), c in cells.items():
            if stream == "actual" and c["bm_nonpos"]:
                sh = cells.get(("shadow", dim, val))
                flagged.append(dict(asset=asset, role=a.get("role", "asset"), dim=dim, value=val, n=c["n"],
                                    bm_actual=c["bm"], bm_shadow=sh and sh["bm"],
                                    both_streams=bool(sh and sh["bm_nonpos"])))
    cols = ["dataset", "asset", "dim", "value", "stream", "n", "wr", "r_payoff", "bm", "mean_r", "m", "qualifying",
            "bm_nonpos", "computed_at"]
    _copy("score.cell_bm", rows, cols, f"DELETE FROM score.cell_bm WHERE dataset = '{dataset}';")
    return dict(cells=len(rows), checks=checks, flagged=flagged)
