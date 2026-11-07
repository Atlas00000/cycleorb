"""INF-P3-T03 / T04: offline L1 feature builder from the bar lake, parity with the EA ledger, future-shift test.

A Python port of Include/Features.mqh (FeaturesRow) and the range / ATR / spread logic of Include/Setup.mqh
(SetupEvaluate). Every lookup is restricted to bars completed at the decision time (range end), so the builder is
point-in-time by construction; future_shift() proves it by deleting every bar after the range end and checking
that nothing changes.
"""
import glob
import json
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from corb import db
from corb.paths import COMMON, RUNS, TOOLS, VAR
from corb.textio import read_text

LAKE = os.path.join(VAR, "lake", "bars")
ZONES = {"LON": "Europe/London", "NY": "America/New_York", "TKY": "Asia/Tokyo"}
PREFIX = {"LON": "InpLon", "NY": "InpNY", "TKY": "InpTky"}
# EA output precision (Features.mqh / Setup.mqh formats) -> parity tolerance = half a unit in the last place
DIGITS = {"atr_pct": 2, "cost_pct": 2, "spread_avg_pt": 1, "vol_pct": 1, "range_atr": 4, "gap_atr": 3,
          "pre_drift_atr": 3, "range_pos_prev": 3, "sma_dist_hi_atr": 3, "sma_dist_lo_atr": 3,
          "ctx1_prevday_atr": 3, "ctx1_lookback_atr": 3, "ctx2_prevday_atr": 3, "ctx2_lookback_atr": 3,
          "ctx3_prevday_atr": 3, "ctx3_lookback_atr": 3}
# Functional tolerance where the tester's own tick-built bars differ marginally from the broker's stored bars:
# vol_pct is a rank among 500 H1 ATR values; 1.0 point = up to 5 ranks (observed misses: 1-3 ranks)
TOLERANCE = {"vol_pct": 1.0}
EXACT = ["trend_side", "brk_prev_high", "brk_prev_low", "inside_prev", "outside_prev", "nr4", "nr7", "dow",
         "ev_tier1_entry", "ev_tier1_hold", "ev_next_min", "ev_first_hold", "opex", "quad_witching", "ctx1_sym",
         "ctx2_sym", "ctx3_sym"]


class Bars:
    """One symbol's bars per timeframe as numpy arrays (time in epoch seconds, server time = UTC)."""

    def __init__(self, symbol, tf=None):
        self.symbol, self.tf = symbol, tf if tf is not None else {}
        if tf is not None:
            return
        for name in ("M1", "M5", "H1", "D1"):
            files = sorted(glob.glob(os.path.join(LAKE, symbol, name, "*.parquet")))
            if not files:
                continue
            df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("time")
            t = df["time"].dt.tz_localize(None).to_numpy().astype("datetime64[s]").astype("int64")  # any unit
            self.tf[name] = {c: (t if c == "time" else df[c].to_numpy()) for c in
                             ("time", "open", "high", "low", "close", "spread")}

    def cut(self, ts):
        """The same bars with everything opening at or after ts deleted (future-shift test)."""
        out = {}
        for name, a in self.tf.items():
            k = np.searchsorted(a["time"], ts, side="left")
            out[name] = {c: v[:k] for c, v in a.items()}
        return Bars(self.symbol, out)

    def last_at_or_before(self, tf, ts):
        """Index of the bar with open time <= ts (CopyRates(sym, tf, ts, 1))."""
        i = np.searchsorted(self.tf[tf]["time"], ts, side="right") - 1
        return i if i >= 0 else None

    PERIOD = {"M1": 60, "M5": 300, "H1": 3600, "D1": 86400}

    def completed_before(self, tf, ts):
        """Shift 1 at time ts: the last bar that opened before the start of the period containing ts. Independent
        of whether the current bar exists in the data (the decision tick opens it)."""
        floor = ts - ts % self.PERIOD[tf]
        i = np.searchsorted(self.tf[tf]["time"], floor, side="left") - 1
        return i if i >= 0 else None


def _atr(b, tf, last, period):
    """MT5 iATR value at bar index `last`: mean of the last `period` true ranges (TR uses the previous close)."""
    h, l, c = b.tf[tf]["high"], b.tf[tf]["low"], b.tf[tf]["close"]
    if last is None or last < period:
        return None
    i = np.arange(last - period + 1, last + 1)
    tr = np.maximum(h[i], c[i - 1]) - np.minimum(l[i], c[i - 1])
    return float(tr.mean())


def _atr_series(b, tf, period):
    h, l, c = b.tf[tf]["high"], b.tf[tf]["low"], b.tf[tf]["close"]
    tr = np.empty(len(h))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    out = np.full(len(h), np.nan)
    cs = np.cumsum(tr)
    out[period - 1:] = (cs[period - 1:] - np.concatenate([[0.0], cs[:-period]])) / period
    return out


def _utc(day, minutes, zone):
    local = datetime.combine(day, time(0, 0), ZoneInfo(zone)) + timedelta(minutes=minutes)
    return int(local.astimezone(timezone.utc).timestamp())


def _hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_events(ccys):
    path = os.path.join(COMMON, "CycleORB", "events.csv")
    out = []
    for line in read_text(path).splitlines()[1:]:
        f = line.split(",")
        if len(f) >= 4 and f[2] == "HIGH" and f[1] in ccys:
            t = int(datetime.strptime(f[0], "%Y.%m.%d %H:%M").replace(tzinfo=timezone.utc).timestamp())
            out.append((t, f"{f[1]} {f[3]}"))
    return sorted(out, key=lambda e: e[0])   # stable: same-time events keep file order (EventsFirst picks the first)


def build_day(b, ctx, events, inputs, setup, day, point, atr_cache):
    """Features for one setup-day; returns {} when the EA would have no range (FeaturesBlank)."""
    p = PREFIX[setup]
    zone = ZONES[setup]
    start = _hhmm(inputs[f"{p}RangeStart"])
    t_rs = _utc(day, start, zone)
    t_re = _utc(day, start + int(inputs[f"{p}RangeMinutes"]), zone)
    t_ee = _utc(day, _hhmm(inputs[f"{p}EntryEnd"]), zone)
    t_ex = _utc(day, _hhmm(inputs[f"{p}Exit"]), zone)
    m1 = b.tf["M1"]
    i0, i1 = np.searchsorted(m1["time"], t_rs), np.searchsorted(m1["time"], t_re)   # [start, end)
    n = i1 - i0
    if n < max(1, int(inputs[f"{p}RangeMinutes"]) // 2):
        return {}
    hi, lo = float(m1["high"][i0:i1].max()), float(m1["low"][i0:i1].min())
    rng = hi - lo
    d1_last = b.completed_before("D1", t_re)
    atr = _atr(b, "D1", d1_last, int(inputs.get("InpATRPeriod", 14)))
    if rng <= 0 or not atr:
        return {}
    spread_pt = float(m1["spread"][i0:i1].sum()) / n
    atr_pct = 100.0 * rng / atr
    out = dict(atr_pct=atr_pct, cost_pct=100.0 * (spread_pt * point + float(inputs.get("InpCommissionPoints", 0))
                                                   * point) / rng, spread_avg_pt=spread_pt, range_atr=atr_pct / 100.0)
    # vol percentile: last 500 completed H1 ATR(20) values
    h1_last = b.completed_before("H1", t_re)
    look, vper = int(inputs.get("InpVolLookback", 500)), int(inputs.get("InpVolATRPeriod", 20))
    if h1_last is not None:
        key = ("H1", vper)
        if key not in atr_cache:
            atr_cache[key] = _atr_series(b, "H1", vper)
        v = atr_cache[key][h1_last - look + 1:h1_last + 1] if h1_last - look + 1 >= 0 else np.array([])
        if len(v) == look and not np.isnan(v).any():
            out["vol_pct"] = 100.0 * float((v <= v[-1]).sum()) / look
    d1 = b.tf["D1"]
    ma_p = int(inputs.get("InpTrendMAPeriod", 20))
    ma = float(d1["close"][d1_last - ma_p + 1:d1_last + 1].mean()) if d1_last + 1 >= ma_p else None
    if ma:
        c = float(d1["close"][d1_last])
        out["trend_side"] = 1 if c > ma else (-1 if c < ma else 0)
        out["sma_dist_hi_atr"], out["sma_dist_lo_atr"] = (hi - ma) / atr, (lo - ma) / atr
    io = b.last_at_or_before("M1", t_rs)
    ip = b.last_at_or_before("M1", t_rs - 3600)
    if d1_last >= 6:
        dd = list(range(d1_last - 6, d1_last + 1))
        pr_h, pr_l, pr_c = float(d1["high"][dd[6]]), float(d1["low"][dd[6]]), float(d1["close"][dd[6]])
        q_h, q_l = float(d1["high"][dd[5]]), float(d1["low"][dd[5]])
        pr = pr_h - pr_l
        rngs = [float(d1["high"][k] - d1["low"][k]) for k in dd[:6]]
        if io is not None:
            out["gap_atr"] = (float(m1["open"][io]) - pr_c) / atr
            if ip is not None:
                out["pre_drift_atr"] = (float(m1["open"][io]) - float(m1["open"][ip])) / atr
        out["range_pos_prev"] = ((hi + lo) / 2.0 - pr_l) / max(pr, point)
        out["brk_prev_high"], out["brk_prev_low"] = int(hi > pr_h), int(lo < pr_l)
        out["inside_prev"] = int(pr_h <= q_h and pr_l >= q_l)
        out["outside_prev"] = int(pr_h > q_h and pr_l < q_l)
        out["nr7"] = int(all(r >= pr for r in rngs))
        out["nr4"] = int(all(r >= pr for r in rngs[3:]))
    out["dow"] = (day.weekday() + 1) % 7
    if events is not None:
        ev = [(t, name) for t, name in events]
        out["ev_tier1_entry"] = sum(1 for t, _ in ev if t_rs <= t < t_ee)
        out["ev_tier1_hold"] = sum(1 for t, _ in ev if t_re <= t < t_ex)
        nxt = [(t - t_re) // 60 for t, _ in ev if 0 <= t - t_re < 24 * 3600]
        out["ev_next_min"] = min(nxt) if nxt else -1
        first = next((name for t, name in ev if t_re <= t < t_ex), "")   # earliest time, file order on ties
        out["ev_first_hold"] = first.replace(",", ";")
    opex = day.weekday() == 4 and 15 <= day.day <= 21
    out["opex"], out["quad_witching"] = int(opex), int(opex and day.month % 3 == 0)
    hours = int(inputs.get("InpAosCtxHours", 0) or 0)
    for k, (sym, cb) in enumerate(ctx, start=1):
        out[f"ctx{k}_sym"] = sym
        if cb is None or "D1" not in cb.tf:
            continue
        cl = cb.completed_before("D1", t_re)
        if cl is None or cl < 14:
            continue
        cd = cb.tf["D1"]
        i = np.arange(cl - 13, cl + 1)
        catr = float((np.maximum(cd["high"][i], cd["close"][i - 1]) - np.minimum(cd["low"][i], cd["close"][i - 1])).mean())
        if catr <= 0:
            continue
        out[f"ctx{k}_prevday_atr"] = (float(cd["close"][cl]) - float(cd["close"][cl - 1])) / catr
        if "M5" in cb.tf:
            a, z = cb.last_at_or_before("M5", t_rs - 1), cb.last_at_or_before("M5", t_rs - hours * 3600 - 1)
            if a is not None and z is not None:
                out[f"ctx{k}_lookback_atr"] = (float(cb.tf["M5"]["close"][a]) - float(cb.tf["M5"]["close"][z])) / catr
    return out


def _run_inputs(run_id):
    with open(os.path.join(RUNS, run_id, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    return meta["inputs"], float(meta["point"]), meta["symbol"]


def _context(run_id):
    inputs, point, symbol = _run_inputs(run_id)
    ctx_syms = [s.strip() for s in (inputs.get("InpAosCtxSymbols") or "").split(",") if s.strip()][:3]
    ccys = {c.strip() for c in (inputs.get("InpAosEventCcy") or "").split(",") if c.strip()}
    key = db.psql(f"SELECT run_key FROM core.run WHERE run_id = '{run_id}';")
    days = [ln.split("\t") for ln in db.psql(f"SELECT event_id, local_day, setup FROM core.decision "
                                              f"WHERE run_key = '{key}' ORDER BY local_day;").splitlines() if ln]
    return dict(inputs=inputs, point=point, key=key, days=days, events=load_events(ccys) if ccys else None,
                bars=Bars(symbol), ctx=[(s, Bars(s)) for s in ctx_syms])


def build_run(run_id, c=None):
    """Offline features for every setup-day of a run (its decisions in core.decision)."""
    c = c or _context(run_id)
    cache, out = {}, {}
    for eid, day, setup in c["days"]:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        out[eid] = build_day(c["bars"], c["ctx"], c["events"], c["inputs"], setup, d, c["point"], cache)
    return c["key"], out


def parity(run_id, built):
    """Offline vs the EA ledger values of the same run."""
    key = db.psql(f"SELECT run_key FROM core.run WHERE run_id = '{run_id}';")
    ea = {}
    for ln in db.psql(f"SELECT event_id, feature, value_num, value_text FROM features.feature_value "
                      f"WHERE run_key = '{key}' AND source = 'ea';").splitlines():
        eid, f, num, text = (ln.split("\t") + ["", "", "", ""])[:4]
        ea.setdefault(eid, {})[f] = float(num) if num != "" else text
    stats = {}
    for eid, want in ea.items():
        got = built.get(eid, {})
        for f, w in want.items():
            if f == "spread_live_pt":
                continue
            s = stats.setdefault(f, dict(n=0, ok=0, missing=0, max_diff=0.0, examples=[]))
            s["n"] += 1
            g = got.get(f)
            if g is None or g == "":
                s["missing"] += 1
                ok = w == "" or w is None
            elif f in DIGITS:
                diff = abs(float(g) - float(w))
                s["max_diff"] = max(s["max_diff"], diff)
                ok = diff <= TOLERANCE.get(f, 0.5 * 10 ** -DIGITS[f]) + 1e-9
            else:
                ok = str(g) == str(w) or (isinstance(w, float) and float(g) == w)
            s["ok"] += ok
            if not ok and len(s["examples"]) < 3:
                s["examples"].append(f"{eid}: offline {g} vs ea {w}")
    return stats


PARITY_ACCEPT, PARITY_REJECT = 0.99, 0.95   # per feature: >= 99 % ok; below 95 % the feature can't be used


def store(run_id, key, built, c):
    """Offline values into features.feature_value (source = offline, as_of = decision = range end)."""
    import csv
    from corb import contract
    rows = []
    for eid, day, setup in c["days"]:
        vals = built.get(eid) or {}
        if not vals:
            continue
        d = datetime.strptime(day, "%Y-%m-%d").date()
        p = PREFIX[setup]
        t_re = _utc(d, _hhmm(c["inputs"][f"{p}RangeStart"]) + int(c["inputs"][f"{p}RangeMinutes"]), ZONES[setup])
        ts = datetime.fromtimestamp(t_re, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for f, v in vals.items():
            if v == "":
                continue   # the EA ledger leaves empty values out too
            num = None if isinstance(v, str) else float(v)
            rows.append(dict(run_key=key, event_id=eid, feature=f, value_num=num,
                             value_text=v if isinstance(v, str) and v != "" else None,
                             as_of_ts=ts, decision_ts=ts, source="offline"))
    bad = contract.validate("feature", rows)
    if bad:
        raise ValueError(f"{len(bad)} contract violations in offline features, e.g. {bad[:2]}")
    path = os.path.join(VAR, "stage", "feature_offline.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = ["run_key", "event_id", "feature", "value_num", "value_text", "as_of_ts", "decision_ts", "source"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    db.psql(f"BEGIN;\nDELETE FROM features.feature_value WHERE run_key = '{key}' AND source = 'offline';\n"
            f"\\copy features.feature_value ({', '.join(cols)}) FROM '/corb/var/stage/feature_offline.csv' "
            f"WITH (FORMAT csv, HEADER true)\nCOMMIT;\n")
    return len(rows)


def run_all(sample=40):
    """Every baseline asset's P1obs ledger run: build, store, parity vs the EA, future-shift test."""
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    per_asset, pooled = {}, {}
    for asset, a in assets.items():
        run_id = a["run_id"] + "_P1obs"
        if not os.path.isdir(os.path.join(RUNS, run_id)):
            continue
        c = _context(run_id)
        key, built = build_run(run_id, c)
        stored = store(run_id, key, built, c)
        st = parity(run_id, built)
        fs = future_shift(run_id, built, c, sample)
        per_asset[asset] = dict(run_id=run_id, days_built=sum(1 for v in built.values() if v), values_stored=stored,
                                parity={f: dict(ok=s["ok"], n=s["n"], max_diff=s["max_diff"], examples=s["examples"])
                                        for f, s in st.items()}, future_shift=fs)
        for f, s in st.items():
            p = pooled.setdefault(f, dict(ok=0, n=0))
            p["ok"] += s["ok"]
            p["n"] += s["n"]
    with open(os.path.join(os.path.dirname(TOOLS), "infra", "features.json"), encoding="utf-8") as f:
        offline = {x["name"]: x["offline"] for x in json.load(f)["features"]}
    for f, p in pooled.items():
        p["share"] = p["ok"] / p["n"] if p["n"] else None
        p["status"] = "not_offline" if not offline.get(f, True) else (
            "ok" if p["share"] >= PARITY_ACCEPT else ("catalogued" if p["share"] >= PARITY_REJECT else "reject"))
    return per_asset, pooled


def future_shift(run_id, built, c=None, sample=40):
    """Rebuild a sample of days with every bar opening at or after the range end deleted (all symbols): the
    features must not change. Calendar features use the scheduled calendar, which is not bar data."""
    c = c or _context(run_id)
    days = {eid: (day, setup) for eid, day, setup in c["days"]}
    eids = sorted(e for e, v in built.items() if v)
    eids = eids[:: max(1, len(eids) // sample)][:sample]
    changed = []
    for eid in eids:
        day, setup = days[eid]
        d = datetime.strptime(day, "%Y-%m-%d").date()
        p = PREFIX[setup]
        cut = _utc(d, _hhmm(c["inputs"][f"{p}RangeStart"]) + int(c["inputs"][f"{p}RangeMinutes"]), ZONES[setup])
        shifted = build_day(c["bars"].cut(cut), [(s, b.cut(cut)) for s, b in c["ctx"]], c["events"], c["inputs"],
                            setup, d, c["point"], {})
        diffs = sorted(f for f in built[eid] if shifted.get(f) != built[eid][f])
        if diffs:
            changed.append(dict(event_id=eid, features=diffs))
    return dict(days_checked=len(eids), days_changed=len(changed), examples=changed[:5])
