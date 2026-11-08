"""INF-P3-T07: engine replica — CycleORB's trading logic on stored M1 bars.

Scope: the engine as configured in the nine baseline presets (one setup per run, every AOS input at its default;
anything else is refused). Per setup-day: SetupEvaluate's filters and order levels, OCO stop orders until entry end,
stop / target / time exit, the monthly cycle (risk money, soft halt, hard flatten, ratchet, last-day rule) and lot
sizing with the broker's minimum lot. Output: run folders in the tester's format (meta.json, events.csv,
decisions.csv) with "source": "replica", so corb_bench and the contract adapter read them unchanged.

Fills on M1 bars (bid OHLC + the bar's spread for the ask): a stop order fills at its price, or at the bar open when
the bar opens through it; stop-loss and target likewise; when both levels of a bar are touched, the one nearer the
open counts first. Time exits close at the open of the first bar at or after the exit time.

parity()   replica vs the native tester run on the tester window (gate below), using the bars as stamped
extend()   the same engine on earlier history converted to UTC: only months whose server clock offset is read
           cleanly from the data (clock_offsets) and that are not next to a clock change
"""
import csv
import glob
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from corb.featbuild import LAKE, PREFIX, ZONES, Bars, _atr, _atr_series, _hhmm
from corb.paths import RUNS, TOOLS, VAR

OUT = os.path.join(VAR, "replica")
# minimum lot, lot step: inferred from every tester run's volumes (smallest volume, gcd of volumes) and the
# lot-minimum skips of the share CFDs (volume 1.00 is the smallest ever filled)
SPECS = {"DE30": (0.1, 0.1), "UK100": (0.1, 0.1), "SPX500": (0.1, 0.1), "JPN225": (0.1, 0.1), "EURUSD": (0.01, 0.01),
         "GBPUSD": (0.01, 0.01), "USDJPY": (0.01, 0.01), "Apple": (1.0, 0.01), "Microsoft": (1.0, 0.01),
         "Exxon": (1.0, 0.01)}
# trade session open (server minutes) where it is later than the quotes: the share CFDs keep fixed 14:30 (US winter
# cash open) all year, so during US DST the EA waits from its 14:00 range end to 14:30 (every late decision time in
# the P1obs ledgers of AAPL and MSFT is 14:30; no other asset evaluates late)
SESSION_OPEN = {"Apple": 870, "Microsoft": 870, "Exxon": 870}
DEFAULT_AOS = {"InpAosLongGate": "0", "InpAosShortGate": "0", "InpAosEventSizeMult": "1.0", "InpAosCancelBeforeMin": "0",
               "InpAosCellAtrMax": "0.0", "InpAosCellMult": "1.0"}
GATE = dict(event_set=0.98, pnl_tol=0.02, pnl_share=0.95, ef_pp=1.0)
HEADER = ["event_id", "magic", "setup", "symbol", "side", "day", "place_time", "entry_time", "entry_requested",
          "entry_price", "exit_time", "exit_price", "exit_type", "close_reason", "initial_stop", "take_profit", "volume",
          "risk_px", "pnl_R", "pnl_ccy_est", "risk_ccy_est", "equity_at_open_est", "risk_pct_est", "atr_pct", "trend",
          "spread_pt", "c_spread_R", "c_slip_R", "slip_entry_R", "hold_min"]
DEC_HEADER = ["date", "setup", "decision", "reason", "atr_pct", "spread_pt", "cost_pct", "range_pt", "risk_money", "trend",
              "sides_placed", "sides_lot_min", "symbol"]


def _f(inputs, k, default):
    v = inputs.get(k)
    return float(v) if v not in (None, "") else default


def _skip_dates(raw):
    out = set()
    for tok in (raw or "").replace(";", ",").replace(" ", ",").split(","):
        tok = tok.strip().replace(".", "").replace("-", "")
        if tok:
            s = tok if len(tok) == 8 else "20" + tok
            out.add(date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    return out


NEW_YORK = ZoneInfo("America/New_York")


def _is_us_dst(utc):
    return datetime.fromtimestamp(utc, timezone.utc).astimezone(NEW_YORK).dst() != timedelta(0)


class Clock:
    """Server time per the EA's inputs (SessionClock.mqh): fixed offset, or GMT+2 / +3 during US DST."""

    def __init__(self, inputs):
        self.fixed = inputs.get("InpServerTZ", "0") == "1"
        self.hours = int(float(inputs.get("InpServerFixedOffsetH", "2")))

    def offset(self, utc):
        if self.fixed:
            return self.hours * 3600
        return (3 if _is_us_dst(utc) else 2) * 3600

    def local_to_server(self, day, minutes, zone):
        loc = datetime.combine(day, datetime.min.time(), ZoneInfo(zone)) + timedelta(minutes=minutes)
        utc = int(loc.astimezone(timezone.utc).timestamp())
        return utc + self.offset(utc)


def _last_trading_day(server_ts):
    d = datetime.fromtimestamp(server_ts, timezone.utc).date()
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return (n.year, n.month) != (d.year, d.month)


class Cycle:
    """Cycle.mqh: monthly capital, risk money, soft halt, hard flatten, ratchet (equity = capital + realized + floating)."""

    def __init__(self, inputs, balance):
        self.i = dict(soft=_f(inputs, "InpSoftHaltPct", 30.0), hard=_f(inputs, "InpHardFlattenPct", 38.0),
                      arm=_f(inputs, "InpRatchetArmPct", 20.0), floor=_f(inputs, "InpRatchetFloorPct", 10.0),
                      trail=_f(inputs, "InpRatchetTrail", 0.5), div=_f(inputs, "InpRiskDivisor", 8.0),
                      maxrisk=_f(inputs, "InpMaxRiskPct", 8.0), fixed=_f(inputs, "InpCycleCapital", 0.0))
        self.balance, self.month, self.state = balance, None, "ACTIVE"

    def roll(self, server_ts):
        ym = datetime.fromtimestamp(server_ts, timezone.utc).strftime("%Y%m")
        if ym != self.month:
            self.month, self.capital = ym, (self.i["fixed"] or self.balance)
            self.realized, self.peak, self.state = 0.0, 0.0, "ACTIVE"
            return True
        return False

    def pct(self, floating=0.0):
        return 100.0 * (self.realized + floating) / self.capital if self.capital > 0 else 0.0

    def update(self, floating=0.0):
        """One tick: returns 'STOP' when the month is flattened."""
        if self.state == "STOPPED":
            return "STOP"
        p = self.pct(floating)
        self.peak = max(self.peak, p)
        if -p >= self.i["hard"]:
            self.state = "STOPPED"
        elif self.peak >= self.i["arm"] and p <= max(self.i["floor"], self.peak * self.i["trail"]):
            self.state = "STOPPED"
        elif self.state == "ACTIVE" and -p >= self.i["soft"]:
            self.state = "HALTED"
        return "STOP" if self.state == "STOPPED" else None

    def close(self, money):
        self.realized += money
        self.balance += money

    def risk_money(self):
        floor_eq = self.capital * (1.0 - self.i["hard"] / 100.0)
        risk = (self.capital + self.realized - floor_eq) / self.i["div"]
        return max(0.0, min(risk, self.capital * self.i["maxrisk"] / 100.0))


def _norm(px, point):
    return round(round(px / point) * point, 10)


def _lots(risk, risk_px, k, symbol, max_lot):
    mn, step = SPECS.get(symbol, (0.01, 0.01))
    if risk <= 0 or risk_px <= 0 or not k:
        return 0.0
    lot = math.floor(risk / (risk_px * k) / step + 1e-9) * step
    lot = min(lot, max_lot)
    return 0.0 if lot < mn - 1e-9 else round(lot, 2)


def _first_fill(m1, k0, sides, point, t_ee):
    """OCO: the first of the armed sides to fill. sides: {+1: entry, -1: entry}. Returns (k, side, fill) or None."""
    t, o, h, l, s = m1["time"], m1["open"], m1["high"], m1["low"], m1["spread"]
    for k in range(k0, len(t)):
        if t[k] >= t_ee:
            return None
        spr = s[k] * point
        hits = []
        if 1 in sides and h[k] + spr >= sides[1]:
            fill = max(sides[1], o[k] + spr) if o[k] + spr >= sides[1] and k > k0 else sides[1]
            hits.append((abs(sides[1] - (o[k] + spr)), 1, fill))
        if -1 in sides and l[k] <= sides[-1]:
            fill = min(sides[-1], o[k]) if o[k] <= sides[-1] and k > k0 else sides[-1]
            hits.append((abs(o[k] - sides[-1]), -1, fill))
        if hits:
            _, side, fill = min(hits)
            return k, side, fill
    return None


def _exit(m1, kf, side, sl, tp, point, t_ex, cycle, lots, kval, fill):
    """From the fill bar: stop-loss / target / time exit / cycle stop. Returns (k, price, how)."""
    t, o, h, l, c, s = m1["time"], m1["open"], m1["high"], m1["low"], m1["close"], m1["spread"]
    for k in range(kf, len(t)):
        spr = s[k] * point
        if k > kf and t[k] >= t_ex:
            return k, o[k] + (spr if side < 0 else 0.0), "TIME"
        if side > 0:
            hit_sl, hit_tp = l[k] <= sl, h[k] >= tp
            if k == kf:
                hit_sl = c[k] <= sl
            if hit_sl and hit_tp:
                hit_sl = abs(o[k] - sl) <= abs(tp - o[k])
                hit_tp = not hit_sl
            if hit_sl:
                return k, (min(sl, o[k]) if k > kf and o[k] < sl else sl), "SL"
            if hit_tp:
                return k, (max(tp, o[k]) if k > kf and o[k] > tp else tp), "TP"
            floating = (c[k] - fill) * lots * kval
        else:
            ask_h, ask_l, ask_o = h[k] + spr, l[k] + spr, o[k] + spr
            hit_sl, hit_tp = ask_h >= sl, ask_l <= tp
            if k == kf:
                hit_sl = c[k] + spr >= sl
            if hit_sl and hit_tp:
                hit_sl = abs(sl - ask_o) <= abs(ask_o - tp)
                hit_tp = not hit_sl
            if hit_sl:
                return k, (max(sl, ask_o) if k > kf and ask_o > sl else sl), "SL"
            if hit_tp:
                return k, (min(tp, ask_o) if k > kf and ask_o < tp else tp), "TP"
            floating = (fill - (c[k] + spr)) * lots * kval
        if cycle.update(floating) == "STOP":
            return k, c[k] + (spr if side < 0 else 0.0), "CYCLE"
    return len(t) - 1, c[-1], "END"


def simulate(inputs, symbol, bars, window, deposit, point, kval, months=None, holiday_rule=False):
    """The engine over `window` (local dates, inclusive). months: optional set of 'YYYY-MM' to keep (extension).
    holiday_rule: treat a day without a bar in the 30 minutes before the exit as a skip date (stands in for the
    preset's holiday list, which starts in 2025-12). Returns (events, decisions, counters, sides)."""
    for k, v in DEFAULT_AOS.items():
        if str(inputs.get(k, v)) not in (v, v.rstrip("0").rstrip(".")):
            raise ValueError(f"replica covers the engine only: {k}={inputs.get(k)}")
    setups = [s for s in ("LON", "NY", "TKY") if inputs.get(f"{PREFIX[s]}Enable", "false") == "true"]
    if len(setups) != 1:
        raise ValueError(f"replica covers one setup per run, got {setups}")
    setup = setups[0]
    p, zone = PREFIX[setup], ZONES[setup]
    clock = Clock(inputs)
    rs, rmin = _hhmm(inputs[f"{p}RangeStart"]), int(inputs[f"{p}RangeMinutes"])
    ee, ex = _hhmm(inputs[f"{p}EntryEnd"]), _hhmm(inputs[f"{p}Exit"])
    magic = int(inputs["InpMagicBase"]) + {"LON": 1, "NY": 2, "TKY": 3}[setup]
    skip = _skip_dates(inputs.get("InpSkipDates"))
    lo_b, hi_b = _f(inputs, "InpMinRangeATRPct", 10.0), _f(inputs, "InpMaxRangeATRPct", 35.0)
    cost_cap, comm = _f(inputs, "InpMaxCostRangePct", 10.0), _f(inputs, "InpCommissionPoints", 0.0)
    min_vol, trend_only = _f(inputs, "InpMinVolPct", 0.0), inputs.get("InpTrendSideOnly", "false") == "true"
    tgt, bsm, brp = _f(inputs, "InpTargetR", 2.0), _f(inputs, "InpBufferSpreadMult", 2.0), _f(inputs, "InpBufferRangePct", 5.0)
    stop_mid, max_lot = inputs.get("InpStopMode", "0") == "1", _f(inputs, "InpMaxLot", 50.0)
    no_last = inputs.get("InpNoEntryLastDay", "true") == "true"
    atr_p, vper, look = int(_f(inputs, "InpATRPeriod", 14)), int(_f(inputs, "InpVolATRPeriod", 20)), int(_f(inputs, "InpVolLookback", 500))
    ma_p = int(_f(inputs, "InpTrendMAPeriod", 20))
    m1, d1 = bars.tf["M1"], bars.tf["D1"]
    h1_atr = _atr_series(bars, "H1", vper) if "H1" in bars.tf else None
    cycle = Cycle(inputs, deposit)
    events, decisions, counters = [], [], {}
    sides = dict(armed=0, lot_min=0)
    busy_until = 0
    day = window[0]
    while day <= window[1]:
        d, day = day, day + timedelta(days=1)
        if d.weekday() >= 5 or (months is not None and d.strftime("%Y-%m") not in months):
            continue
        t_rs, t_re = clock.local_to_server(d, rs, zone), clock.local_to_server(d, rs + rmin, zone)
        t_ee, t_ex = clock.local_to_server(d, ee, zone), clock.local_to_server(d, ex, zone)
        t_open = t_re
        if symbol in SESSION_OPEN:
            t_open = max(t_re, t_re - t_re % 86400 + SESSION_OPEN[symbol] * 60)
        ke = int(np.searchsorted(m1["time"], t_open))
        if ke >= len(m1["time"]) or m1["time"][ke] >= t_ee:
            continue                                   # no tick in the entry window: the EA never evaluates
        t_ev = int(m1["time"][ke])
        cycle.roll(t_ev)
        dec = dict(date=d.isoformat(), setup=setup, decision="SKIP", reason="", atr_pct="", spread_pt="", cost_pct="",
                   range_pt="", risk_money="", trend="", sides_placed=0, sides_lot_min=0, symbol=symbol)

        def done(reason):
            dec["reason"] = reason
            decisions.append(dec)
            counters[f"skip_{reason}"] = counters.get(f"skip_{reason}", 0) + 1

        if d in skip:
            done("skip_date")
            continue
        if holiday_rule:
            kx = int(np.searchsorted(m1["time"], t_ex - 1800))
            if kx >= len(m1["time"]) or m1["time"][kx] >= t_ex:
                done("skip_date")
                continue
        if cycle.state != "ACTIVE":
            done("cycle")
            continue
        if no_last and _last_trading_day(t_ev):
            done("last_day")
            continue
        if t_ev < busy_until:
            done("already_traded")
            continue
        i0, i1 = int(np.searchsorted(m1["time"], t_rs)), int(np.searchsorted(m1["time"], t_re))
        n = i1 - i0
        if n < max(1, rmin // 2):
            done("missing_bars")
            continue
        hi, lo = float(m1["high"][i0:i1].max()), float(m1["low"][i0:i1].min())
        rng = hi - lo
        if rng <= 0:
            done("zero_range")
            continue
        atr = _atr(bars, "D1", bars.completed_before("D1", t_ev), atr_p)
        if not atr:
            done("warmup")
            continue
        spr_sum = float(m1["spread"][i0:i1].sum())
        spread = spr_sum / n * point if spr_sum > 0 else float(m1["spread"][ke]) * point
        atr_pct, cost_pct = 100.0 * rng / atr, 100.0 * (spread + comm * point) / rng
        dec.update(atr_pct=round(atr_pct, 1), spread_pt=round(spread / point, 1), cost_pct=round(cost_pct, 1),
                   range_pt=round(rng / point))
        if atr_pct < lo_b or atr_pct > hi_b:
            done("atr_band_low" if atr_pct < lo_b else "atr_band_high")
            continue
        if cost_pct > cost_cap:
            done("cost_cap")
            continue
        if min_vol > 0:
            hl = bars.completed_before("H1", t_ev)
            v = h1_atr[hl - look + 1:hl + 1] if hl is not None and hl - look + 1 >= 0 else np.array([])
            if len(v) != look or np.isnan(v).any():
                done("warmup")
                continue
            if 100.0 * float((v <= v[-1]).sum()) / look < min_vol:
                done("vol_floor")
                continue
        trend = 0
        if trend_only:
            dl = bars.completed_before("D1", t_ev)
            if dl is None or dl + 1 < ma_p:
                done("warmup")
                continue
            ma, cl = float(d1["close"][dl - ma_p + 1:dl + 1].mean()), float(d1["close"][dl])
            trend = 1 if cl > ma else (-1 if cl < ma else 0)
            if trend == 0:
                done("trend_flat")
                continue
        buffer = max(bsm * spread, rng * brp / 100.0)
        mid = (hi + lo) / 2.0
        b_e, s_e = _norm(hi + buffer, point), _norm(lo - buffer, point)
        b_sl, s_sl = _norm(mid if stop_mid else lo, point), _norm(mid if stop_mid else hi, point)
        b_tp, s_tp = _norm(b_e + tgt * (b_e - b_sl), point), _norm(s_e - tgt * (s_sl - s_e), point)
        risk = cycle.risk_money()
        dec.update(decision="ARMED", risk_money=round(risk, 2), trend=trend)
        bid = float(m1["open"][ke])
        ask = bid + float(m1["spread"][ke]) * point
        armed, lots = {}, {}
        for side, e, sl, tp, mkt in ((1, b_e, b_sl, b_tp, ask), (-1, s_e, s_sl, s_tp, bid)):
            if trend_only and side != trend:
                continue
            if not ((e - mkt > 0) if side > 0 else (mkt - e > 0)):
                counters["skip_price_through"] = counters.get("skip_price_through", 0) + 1
                continue
            if abs(tp - e) < abs(e - sl) - point / 2.0:
                continue
            sides["armed"] += 1
            lot = _lots(risk, abs(e - sl), kval, symbol, max_lot)
            if lot <= 0:
                sides["lot_min"] += 1
                dec["sides_lot_min"] += 1
                counters["skip_lot_min"] = counters.get("skip_lot_min", 0) + 1
                continue
            armed[side], lots[side] = e, lot
        dec["sides_placed"] = len(armed)
        decisions.append(dec)
        if not armed:
            continue
        hit = _first_fill(m1, ke, armed, point, t_ee)
        if not hit:
            continue
        kf, side, fill = hit
        e, sl, tp = (b_e, b_sl, b_tp) if side > 0 else (s_e, s_sl, s_tp)
        kx, px, how = _exit(m1, kf, side, sl, tp, point, t_ex, cycle, lots[side], kval, fill)
        risk_px = abs(e - sl)
        money = side * (px - fill) * lots[side] * kval
        eq_open = cycle.capital + cycle.realized
        cycle.close(money)
        cycle.update(0.0)
        busy_until = int(m1["time"][kx])
        spx = spread
        if kx < len(m1["time"]) and datetime.fromtimestamp(int(m1["time"][kx]), timezone.utc).date() > \
                datetime.fromtimestamp(t_ex, timezone.utc).date():
            counters["close_fail"] = counters.get("close_fail", 0) + 1
        ts = lambda i: datetime.fromtimestamp(int(m1["time"][i]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        events.append(dict(
            event_id=f"{magic}-{d.strftime('%Y%m%d')}", magic=magic, setup=setup, symbol=symbol,
            side="buy" if side > 0 else "sell", day=d.isoformat(), place_time=ts(ke), entry_time=ts(kf),
            entry_requested=e, entry_price=round(fill, 10), exit_time=ts(kx), exit_price=round(px, 10), exit_type=how,
            close_reason=f"{setup} time exit" if how == "TIME" else "", initial_stop=sl, take_profit=tp,
            volume=lots[side], risk_px=round(risk_px, 10), pnl_R=round(side * (px - fill) / risk_px, 6),
            pnl_ccy_est=round(money, 2), risk_ccy_est=round(lots[side] * risk_px * kval, 2),
            equity_at_open_est=round(eq_open, 2), risk_pct_est=round(100 * lots[side] * risk_px * kval / eq_open, 4),
            atr_pct=round(atr_pct, 1), trend=trend, spread_pt=round(spx / point, 1),
            c_spread_R=round(spx / risk_px, 6), c_slip_R=round(0.5 * spx * (1 + (how != "TP")) / risk_px, 6),
            slip_entry_R=round(side * (fill - e) / risk_px, 6),
            hold_min=round((int(m1["time"][kx]) - int(m1["time"][kf])) / 60.0, 1)))
    return events, decisions, counters, sides, cycle.balance


def _native(asset):
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        a = json.load(f)["assets"][asset]
    d = os.path.join(RUNS, a["run_id"])
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        return a, d, json.load(f)


def write_run(run_id, meta_in, window, events, decisions, counters, sides, final, extra):
    d = os.path.join(OUT, "runs", run_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "events.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(events)
    with open(os.path.join(d, "decisions.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DEC_HEADER)
        w.writeheader()
        w.writerows(decisions)
    meta = dict(run_id=run_id, symbol=meta_in["symbol"], version=meta_in["version"], magic_base=meta_in["magic_base"],
                window=[window[0].isoformat(), window[1].isoformat()], deposit=meta_in["deposit"], final=round(final, 2),
                point=meta_in["point"], usd_per_price_lot=meta_in.get("usd_per_price_lot"), n_events=len(events),
                armed_days=sum(1 for x in decisions if x["decision"] == "ARMED"), sides_armed=sides["armed"],
                sides_lot_min=sides["lot_min"], counters=counters, inputs=meta_in["inputs"], setups=meta_in["setups"],
                source="replica", **extra)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return d, meta


def run_asset(asset):
    """Replica of one baseline on its tester window, bars as stamped (what the tester saw)."""
    a, nd, meta = _native(asset)
    window = (date.fromisoformat(meta["window"][0]), date.fromisoformat(meta["window"][1]))
    bars = Bars(meta["symbol"])
    ev, dec, cnt, sides, final = simulate(meta["inputs"], meta["symbol"], bars, window, meta["deposit"], meta["point"],
                                          meta["usd_per_price_lot"])
    return write_run(a["run_id"] + "_REPLICA", meta, window, ev, dec, cnt, sides, final, dict(native_run=a["run_id"]))


def _load_events(d):
    with open(os.path.join(d, "events.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parity_asset(asset):
    from corb_bench import load_run, score
    a, nd, nmeta = _native(asset)
    rd, rmeta = run_asset(asset)
    nat = {(e["event_id"], e["side"]): float(e["pnl_R"]) for e in _load_events(nd)}
    rep = {(e["event_id"], e["side"]): float(e["pnl_R"]) for e in _load_events(rd)}
    both = set(nat) & set(rep)
    union = set(nat) | set(rep)
    diffs = sorted(abs(nat[k] - rep[k]) for k in both)
    within = sum(x <= GATE["pnl_tol"] for x in diffs)
    ef = {}
    for name, d in (("native", nd), ("replica", rd)):
        m, e = load_run(d)
        ef[name] = score(m, e, a["f_op"], mc_iters=200)["EF"] if e else None
    out = dict(asset=asset, role=a.get("role", "asset"), native_n=len(nat), replica_n=len(rep), matched=len(both),
               event_set=len(both) / len(union) if union else 1.0, pnl_within=within / len(both) if both else 0.0,
               pnl_median_diff=float(np.median(diffs)) if diffs else None, EF_native=ef["native"], EF_replica=ef["replica"],
               only_native=sorted(k[0] for k in set(nat) - set(rep))[:8],
               only_replica=sorted(k[0] for k in set(rep) - set(nat))[:8],
               worst=[dict(event_id=k[0], native=nat[k], replica=rep[k]) for k in
                      sorted(both, key=lambda k: -abs(nat[k] - rep[k]))[:5]])
    efd = None if None in ef.values() else 100 * abs(ef["native"] - ef["replica"])
    out["EF_diff_pp"] = efd
    out["pass"] = (out["event_set"] >= GATE["event_set"] and out["pnl_within"] >= GATE["pnl_share"]
                   and efd is not None and efd <= GATE["ef_pp"]
                   and (out["role"] != "control" or (ef["replica"] is not None and ef["replica"] <= 0)))
    return out


def parity():
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = list(json.load(f)["assets"])
    return [parity_asset(a) for a in assets]


# ---------------------------------------------------------------- extension: earlier history in UTC
ANCHORS = {"SPX500": ("America/New_York", 570), "Apple": ("America/New_York", 570),
           "Microsoft": ("America/New_York", 570), "Exxon": ("America/New_York", 570),
           "EURUSD": ("America/New_York", 510), "JPN225": ("Asia/Tokyo", 540)}


def clock_offsets(symbol):
    """Server clock offset (hours) per month, read from the data: the minute of the largest mean M1 range vs a fixed
    local anchor (US cash open 09:30 New York, US data 08:30 New York, Tokyo open 09:00). None = not readable."""
    tz, mins = ANCHORS[symbol]
    out = {}
    for f in sorted(glob.glob(os.path.join(LAKE, symbol, "M1", "*.parquet"))):
        d = pd.read_parquet(f, columns=["time", "high", "low"])
        t = d["time"].dt.tz_localize(None)
        d = d.assign(r=d["high"] - d["low"], ym=t.dt.strftime("%Y-%m"), m=t.dt.hour * 60 + t.dt.minute)
        for ym, g in d.groupby("ym"):
            y, mo = map(int, ym.split("-"))
            loc = datetime(y, mo, 15, mins // 60, mins % 60, tzinfo=ZoneInfo(tz))
            utc_m = (mins - loc.utcoffset().total_seconds() / 60) % 1440
            peak = int(g.groupby("m")["r"].mean().idxmax())
            off = ((peak - utc_m + 720) % 1440 - 720) / 60
            out[ym] = int(off) if off == int(off) and abs(off) <= 4 else None
    return out


def clean_months(offsets):
    """Months whose offset is known and equal to both neighbours' (not next to a clock change)."""
    keys = sorted(offsets)
    keep = set()
    for i, ym in enumerate(keys):
        o = offsets[ym]
        if o is None or i == 0 or i == len(keys) - 1:
            continue
        if offsets[keys[i - 1]] == o and offsets[keys[i + 1]] == o:
            keep.add(ym)
    return keep


def _resample(t, o, h, l, c, s, period):
    key = t - t % period
    idx = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    end = np.r_[idx[1:], len(t)]
    return dict(time=key[idx], open=o[idx], high=np.maximum.reduceat(h, idx), low=np.minimum.reduceat(l, idx),
                close=c[end - 1], spread=s[idx])


def utc_bars(symbol, offsets):
    """M1 shifted to UTC with each month's offset (nearest known month where unreadable); H1 / D1 rebuilt from it."""
    raw = Bars(symbol).tf["M1"]
    t = raw["time"]
    ym = pd.to_datetime(t, unit="s").strftime("%Y-%m").to_numpy()
    known = sorted(k for k, v in offsets.items() if v is not None)
    fill = {}
    for k in sorted(offsets):
        if offsets[k] is not None:
            fill[k] = offsets[k]
        else:
            near = min(known, key=lambda x: abs(int(x[:4]) * 12 + int(x[5:]) - int(k[:4]) * 12 - int(k[5:])))
            fill[k] = offsets[near]
    shift = np.array([fill.get(m, 0) for m in ym], dtype="int64") * 3600
    tu = t - shift
    order = np.argsort(tu, kind="stable")
    m1 = {c: raw[c][order] for c in raw}
    m1["time"] = tu[order]
    tf = dict(M1=m1)
    for name, per in (("H1", 3600), ("D1", 86400)):
        tf[name] = _resample(m1["time"], m1["open"], m1["high"], m1["low"], m1["close"], m1["spread"], per)
    return Bars(symbol, tf)


EXTEND = ["EURUSD-NY", "EURUSD-LON0700", "US500", "JP225", "CTRL-AAPL", "CTRL-MSFT", "CTRL-XOM"]


def extend_asset(asset):
    """The baseline preset on the history before its tester window, in UTC, clean months only."""
    a, nd, meta = _native(asset)
    sym = meta["symbol"]
    offsets = clock_offsets(sym)
    months = clean_months(offsets)
    start = date.fromisoformat(meta["window"][0])
    months = {m for m in months if m < start.strftime("%Y-%m")}
    if not months:
        return None
    inputs = dict(meta["inputs"], InpServerTZ="1", InpServerFixedOffsetH="0")
    window = (date.fromisoformat(min(months) + "-01"), start - timedelta(days=1))
    bars = utc_bars(sym, offsets)
    ev, dec, cnt, sides, final = simulate(inputs, sym, bars, window, meta["deposit"], meta["point"],
                                          meta["usd_per_price_lot"], months=months, holiday_rule=True)
    run_id = f"replica_{sym}_{meta['magic_base']}_{window[0]:%Y-%m-%d}_{window[1]:%Y-%m-%d}_{int(meta['deposit'])}"
    d, m = write_run(run_id, meta, window, ev, dec, cnt, sides, final,
                     dict(native_run=a["run_id"], extension=True, clock_offsets=offsets, months_used=sorted(months),
                          clock_note="bars shifted to UTC per month; H1 / D1 rebuilt from M1"))
    return d, m
