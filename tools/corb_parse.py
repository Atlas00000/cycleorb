"""CycleORB journal adapter (edge_framework.md §2.3).

Reads a Strategy Tester journal (Tester/logs/YYYYMMDD.log, UTF-16) and writes one folder per tester run:
  <out>/<run_id>/meta.json      inputs, version, window, deposit, final balance, counters
  <out>/<run_id>/events.csv     one row per trade event (event_id = magic-YYYYMMDD of the setup day)
  <out>/<run_id>/decisions.csv  one row per setup-day decision (ARMED / SKIP + reason)

Usage:
  python corb_parse.py <journal.log> [--out ../tester/aos/runs] [--version 1.09] [--symbol SPX500]
"""
import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime

RE_START = re.compile(r"\t(\S+),M\d+: testing of .* from (\d{4}\.\d\d\.\d\d) \S+ to (\d{4}\.\d\d\.\d\d) \S+ started with inputs")
RE_INPUT = re.compile(r"\t  (Inp\w+)=(.*)$")
RE_DEPOSIT = re.compile(r"initial deposit ([\d\.]+) (\w+)")
RE_EVENT = re.compile(r"\t(\d{4}\.\d\d\.\d\d \d\d:\d\d:\d\d)\s+(.*)$")
RE_FINAL = re.compile(r"final balance ([\d\.]+)")
RE_VERSION = re.compile(r"\[CycleORB\] Init OK v([\d\.]+)")
RE_PLACE = re.compile(r"\[CycleORB\] PLACE (BUY|SELL)_STOP lots=([\d\.]+) @([\d\.]+) sl=([\d\.]+) tp=([\d\.]+) magic=(\d+)")
RE_TRIG = re.compile(r"order \[#(\d+) (buy|sell) stop ([\d\.]+) \S+ at ([\d\.]+)\] triggered")
RE_DEAL = re.compile(r"deal #\d+ (buy|sell) ([\d\.]+) \S+ at ([\d\.]+) done \(based on order #(\d+)\)")
RE_SL = re.compile(r"stop loss triggered #(\d+)")
RE_TP = re.compile(r"take profit triggered #(\d+)")
RE_MCLOSE = re.compile(r"market (?:buy|sell) [\d\.]+ \S+, close #(\d+)")
RE_RANGE = re.compile(r"\[CycleORB\] RANGE (\w+) (\d{4}\.\d\d\.\d\d) \S+ hi=([\d\.]+) lo=([\d\.]+) range=(\d+)pt atr%=([\d\.]+) "
                      r"spread=([\d\.]+)pt .*cost%=([\d\.]+) buffer=(\d+)pt risk=([\d\.]+) trend=(-?\d)")
RE_SKIP = re.compile(r"\[CycleORB\] SKIP (\w+)(?: (\d{4}\.\d\d\.\d\d))?(.*)$")
RE_CYCLE = re.compile(r"\[CycleORB\] CYCLE_(END|PARTIAL) (\d+) capital=([\d\.\-]+) realized=([\d\.\-]+) .*pnl=([\d\.\-]+)% peak=([\d\.\-]+)%")
RE_CLOSEFAIL = re.compile(r"\[CycleORB\] CLOSE FAIL")
RE_CLOSE_LOG = re.compile(r"\[CycleORB\] CLOSE position #(\d+) magic=\d+ \((.*)\)")
RE_SLIP_ABORT = re.compile(r"\[CycleORB\] GUARD SLIP_ABORT position #(\d+)")

SETUP_BY_OFFSET = {1: "LON", 2: "NY", 3: "TKY"}


def read_journal(path):
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16").splitlines()
    return raw.decode("utf-8-sig", errors="replace").splitlines()


def skip_reason(text, inputs):
    if "range/ATR outside band" in text:
        a = re.search(r"atr%=([\d\.]+)", text)
        low = a and float(a.group(1)) < float(inputs.get("InpMinRangeATRPct", 0))
        return "atr_band_low" if low else "atr_band_high"
    for key, code in (("H1 vol below", "vol_floor"), ("cost too high", "cost_cap"), ("last trading day", "last_day"),
                      ("lot below broker minimum", "lot_min"), ("already at/through", "price_through"),
                      ("TP distance", "tp_lt_sl"), ("on its SMA", "trend_flat"), ("already traded", "already_traded"),
                      ("M1 bars", "missing_bars"), ("skip date", "skip_date"), ("percentile unavailable", "warmup"),
                      ("ATR unavailable", "warmup"), ("trend unavailable", "warmup"), ("cycle", "cycle")):
        if key in text:
            return code
    return "other"


def new_run(symbol, d_from, d_to, deposit):
    return dict(symbol=symbol, window=[d_from.replace(".", "-"), d_to.replace(".", "-")], deposit=deposit, inputs={},
                version=None, final=None, places=[], trades={}, decisions=[], cycles=[], counters=Counter(),
                closefail_dates=Counter(), point=None)


def parse(lines):
    runs, cur, pend, deposit = [], None, None, None
    for ln in lines:
        m = RE_DEPOSIT.search(ln)
        if m:
            deposit = float(m.group(1))
        m = RE_START.search(ln)
        if m:
            cur = new_run(m.group(1), m.group(2), m.group(3), deposit)
            runs.append(cur)
            pend = None
            continue
        if cur is None:
            continue
        m = RE_INPUT.search(ln)
        if m:
            cur["inputs"][m.group(1)] = m.group(2)
            continue
        m = RE_FINAL.search(ln)
        if m:
            cur["final"] = float(m.group(1))
            continue
        m = RE_EVENT.search(ln)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y.%m.%d %H:%M:%S")
        msg = m.group(2)
        if (mm := RE_VERSION.search(msg)):
            cur["version"] = mm.group(1)
        elif (mm := RE_PLACE.search(msg)):
            cur["places"].append(dict(t=t, side=mm.group(1), lots=float(mm.group(2)), entry=float(mm.group(3)),
                                      sl=float(mm.group(4)), tp=float(mm.group(5)), magic=int(mm.group(6)),
                                      used=False, decision=cur["decisions"][-1] if cur["decisions"] else None))
            if cur["decisions"]:
                cur["decisions"][-1]["sides_placed"] += 1
        elif (mm := RE_TRIG.search(msg)):
            tk, side, lots, price = mm.group(1), mm.group(2).upper(), float(mm.group(3)), float(mm.group(4))
            pl = next(p for p in reversed(cur["places"]) if not p["used"] and p["side"] == side
                      and abs(p["entry"] - price) < 1e-9 and abs(p["lots"] - lots) < 1e-9)
            pl["used"] = True
            dec = pl["decision"] or {}
            cur["trades"][tk] = dict(ticket=tk, magic=pl["magic"], side=side, lots=lots, entry_plan=pl["entry"],
                                     sl=pl["sl"], tp=pl["tp"], t_place=pl["t"], t_in=t, fill=None, exit=None,
                                     t_out=None, how=None, day=dec.get("date", t.strftime("%Y-%m-%d")),
                                     atr_pct=dec.get("atr_pct"), spread_pt=dec.get("spread_pt"),
                                     trend=dec.get("trend"), close_reason=None)
            pend = ("in", tk)
        elif (mm := RE_SL.search(msg)):
            pend = ("SL", mm.group(1))
        elif (mm := RE_TP.search(msg)):
            pend = ("TP", mm.group(1))
        elif (mm := RE_MCLOSE.search(msg)):
            pend = ("TIME", mm.group(1))
        elif (mm := RE_DEAL.search(msg)):
            if pend is None or pend[1] not in cur["trades"]:
                continue
            kind, tk = pend
            tr = cur["trades"][tk]
            if kind == "in":
                tr["fill"] = float(mm.group(3))
            else:
                tr["exit"], tr["t_out"], tr["how"] = float(mm.group(3)), t, kind
            pend = None
        elif (mm := RE_CLOSE_LOG.search(msg)):
            if mm.group(1) in cur["trades"]:
                cur["trades"][mm.group(1)]["close_reason"] = mm.group(2)
        elif (mm := RE_SLIP_ABORT.search(msg)):
            if mm.group(1) in cur["trades"]:
                cur["trades"][mm.group(1)]["close_reason"] = "SLIP_ABORT"
        elif (mm := RE_RANGE.search(msg)):
            hi, lo, rpt = float(mm.group(3)), float(mm.group(4)), int(mm.group(5))
            if rpt > 0 and cur["point"] is None:
                cur["point"] = round((hi - lo) / rpt, 10)
            cur["decisions"].append(dict(date=mm.group(2).replace(".", "-"), setup=mm.group(1), decision="ARMED",
                                         reason="", atr_pct=float(mm.group(6)), spread_pt=float(mm.group(7)),
                                         cost_pct=float(mm.group(8)), range_pt=rpt, risk_money=float(mm.group(10)),
                                         trend=int(mm.group(11)), sides_placed=0, sides_lot_min=0))
        elif (mm := RE_SKIP.search(msg)):
            reason = skip_reason(msg, cur["inputs"])
            cur["counters"]["skip_" + reason] += 1
            if reason in ("lot_min", "price_through", "tp_lt_sl") and cur["decisions"]:
                # side-level skip: belongs to the day's ARMED row, not a new decision
                if reason == "lot_min":
                    cur["decisions"][-1]["sides_lot_min"] += 1
                else:
                    cur["decisions"][-1]["reason"] = (cur["decisions"][-1]["reason"] + " " + reason).strip()
                continue
            date = (mm.group(2) or t.strftime("%Y.%m.%d")).replace(".", "-")
            a = re.search(r"atr%=([\d\.]+)", msg)
            cur["decisions"].append(dict(date=date, setup=mm.group(1), decision="SKIP", reason=reason,
                                         atr_pct=float(a.group(1)) if a else None, spread_pt=None, cost_pct=None,
                                         range_pt=None, risk_money=None, trend=None, sides_placed=0, sides_lot_min=0))
        elif (mm := RE_CYCLE.search(msg)):
            cur["cycles"].append(dict(kind=mm.group(1), month=mm.group(2), capital=float(mm.group(3)),
                                      realized=float(mm.group(4)), pnl_pct=float(mm.group(5)), peak_pct=float(mm.group(6))))
        elif RE_CLOSEFAIL.search(msg):
            cur["counters"]["close_fail"] += 1
            cur["closefail_dates"][t.strftime("%Y-%m-%d")] += 1
    return runs


def finish(run):
    """Compute R, costs and the USD reconciliation for one run; returns (meta, events, decisions)."""
    inp = run["inputs"]
    base = int(inp.get("InpMagicBase", 0))
    trades = sorted((t for t in run["trades"].values() if t["exit"] is not None), key=lambda x: x["t_in"])
    pt = run["point"] or 0.0
    for t in trades:
        d = 1 if t["side"] == "BUY" else -1
        t["risk_px"] = abs(t["entry_plan"] - t["sl"])
        t["R"] = d * (t["exit"] - t["fill"]) / t["risk_px"]
        t["px_pnl"] = d * (t["exit"] - t["fill"]) * t["lots"]
        spread_px = (t["spread_pt"] or 0.0) * pt
        t["c_spread_R"] = spread_px / t["risk_px"]
        t["c_slip_R"] = 0.5 * spread_px * (1 + (t["how"] != "TP")) / t["risk_px"]
        t["slip_entry_R"] = d * (t["fill"] - t["entry_plan"]) / t["risk_px"]
    deposit = run["deposit"] or 0.0
    tot_px = sum(t["px_pnl"] for t in trades)
    k = (run["final"] - deposit) / tot_px if trades and tot_px and run["final"] is not None else None
    eq = deposit
    events = []
    for t in trades:
        usd = t["px_pnl"] * k if k else None
        risk_ccy = t["lots"] * t["risk_px"] * k if k else None
        events.append(dict(
            event_id=f"{t['magic']}-{t['day'].replace('-', '')}", magic=t["magic"],
            setup=SETUP_BY_OFFSET.get(t["magic"] - base, "?"), symbol=run["symbol"], side=t["side"].lower(),
            day=t["day"], place_time=t["t_place"].isoformat(sep=" "), entry_time=t["t_in"].isoformat(sep=" "),
            entry_requested=t["entry_plan"], entry_price=t["fill"], exit_time=t["t_out"].isoformat(sep=" "),
            exit_price=t["exit"], exit_type=t["how"], close_reason=t["close_reason"] or "", initial_stop=t["sl"],
            take_profit=t["tp"], volume=t["lots"], risk_px=round(t["risk_px"], 10), pnl_R=round(t["R"], 6),
            pnl_ccy_est=None if usd is None else round(usd, 2), risk_ccy_est=None if risk_ccy is None else round(risk_ccy, 2),
            equity_at_open_est=round(eq, 2), risk_pct_est=None if risk_ccy is None else round(100 * risk_ccy / eq, 4),
            atr_pct=t["atr_pct"], trend=t["trend"], spread_pt=t["spread_pt"], c_spread_R=round(t["c_spread_R"], 6),
            c_slip_R=round(t["c_slip_R"], 6), slip_entry_R=round(t["slip_entry_R"], 6),
            hold_min=round((t["t_out"] - t["t_in"]).total_seconds() / 60, 1)))
        if usd is not None:
            eq += usd
    version = run["version"] or "<=1.08"
    run_id = f"v{version.replace('<=', 'le')}_{run['symbol']}_{base}_{run['window'][0]}_{run['window'][1]}_{int(deposit)}"
    if inp.get("InpAosRunTag"):
        run_id += "_" + inp["InpAosRunTag"]
    sides_armed = sum(2 if (d["decision"] == "ARMED" and inp.get("InpTrendSideOnly") != "true") else
                      (1 if d["decision"] == "ARMED" else 0) for d in run["decisions"])
    meta = dict(run_id=run_id, symbol=run["symbol"], version=version, magic_base=base, window=run["window"],
                deposit=deposit, final=run["final"], point=pt, usd_per_price_lot=k, n_events=len(events),
                armed_days=sum(1 for d in run["decisions"] if d["decision"] == "ARMED"),
                sides_armed=sides_armed, sides_lot_min=run["counters"].get("skip_lot_min", 0),
                counters=dict(run["counters"]), closefail_dates=dict(run["closefail_dates"]), cycles=run["cycles"],
                inputs=run["inputs"], setups=[name for key, name in (("InpLonEnable", "LON"), ("InpNYEnable", "NY"),
                                                                     ("InpTkyEnable", "TKY")) if inp.get(key) == "true"])
    decisions = [dict(d, symbol=run["symbol"]) for d in run["decisions"]]
    return meta, events, decisions


def write_run(out_dir, meta, events, decisions, source):
    path = os.path.join(out_dir, meta["run_id"])
    os.makedirs(path, exist_ok=True)
    meta = dict(meta, source=source)
    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    for name, rows in (("events.csv", events), ("decisions.csv", decisions)):
        with open(os.path.join(path, name), "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("journal")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "tester", "aos", "runs"))
    ap.add_argument("--version", help="only runs whose Init OK line shows this version (e.g. 1.09); '<=1.08' for older")
    ap.add_argument("--symbol", help="only runs on this symbol")
    a = ap.parse_args()
    lines = read_journal(a.journal)
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]
    for run in parse(lines):
        meta, events, decisions = finish(run)
        if a.version and meta["version"] != a.version:
            continue
        if a.symbol and meta["symbol"] != a.symbol:
            continue
        path = write_run(a.out, meta, events, decisions,
                         dict(journal=os.path.abspath(a.journal), journal_sha256_16=digest))
        print(f"{meta['run_id']:<60} events={meta['n_events']:>4} final={meta['final']} -> {os.path.relpath(path)}")


if __name__ == "__main__":
    main()
