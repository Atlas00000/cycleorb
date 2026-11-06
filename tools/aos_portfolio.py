"""AOS-P6-T05: portfolio replay of the per-asset streams, merged by time.

Each asset's trades come from its own tester run (events.csv + ledger_decisions.csv). Every armed setup-day reserves
its risk f (the trade's effective risk %, or the asset's median when it never filled) from arming time until its exit
(or entry end when unfilled), exactly as the EA's terminal-wide reservation would.
  heat cap   : at arming, f is scaled down so that the sum of active reservations stays <= CAP % of equity
  bucket     : DE40 + UK100 (Europe open): when the second same-direction fill of the morning arrives, it is
               halved (mode half) or withheld (mode skip)
Portfolio return = sum of f x scale x R, compounded in exit-time order. Monte Carlo = MC-2 block bootstrap (block 10).

Usage:  python aos_portfolio.py --streams aos_portfolio_streams.json [--cap 3] [--json out.json]
"""
import argparse
import csv
import json
import os
import random
import statistics as st
from datetime import datetime

import corb_metrics as cm

HERE = os.path.dirname(os.path.abspath(__file__))


def _t(s, fmt="%Y-%m-%d %H:%M:%S"):
    return datetime.strptime(s, fmt)


def load_stream(key, run_dir, bucket):
    with open(os.path.join(run_dir, "events.csv"), encoding="utf-8") as f:
        events = {e["event_id"]: e for e in csv.DictReader(f)}
    with open(os.path.join(run_dir, "ledger_decisions.csv"), encoding="utf-8", errors="replace") as f:
        decisions = [d for d in csv.DictReader(f) if d["decision"] == "ARMED"
                     and (d["placed_buy"] == "1" or d["placed_sell"] == "1")]
    risks = [float(e["risk_pct_est"]) / 100 for e in events.values() if e.get("risk_pct_est")]
    f_med = st.median(risks) if risks else 0.01
    out = []
    for d in decisions:
        e = events.get(d["event_id"])
        arm = _t(d["time"], "%Y.%m.%d %H:%M:%S")
        if e:
            out.append(dict(asset=key, bucket=bucket, id=d["event_id"], arm=arm, entry=_t(e["entry_time"]),
                            end=_t(e["exit_time"]), f=float(e["risk_pct_est"]) / 100, R=float(e["pnl_R"]),
                            side=e["side"], filled=True))
        else:
            out.append(dict(asset=key, bucket=bucket, id=d["event_id"], arm=arm, entry=None,
                            end=_t(d["entry_end"], "%Y.%m.%d %H:%M:%S"), f=f_med, R=0.0, side="", filled=False))
    return out


def replay(rows, cap=None, bucket_mode=None):
    rows = sorted(rows, key=lambda r: r["arm"])
    active = []          # (end, f_reserved)
    bind = 0
    for r in rows:
        active = [a for a in active if a[0] > r["arm"]]
        scale = 1.0
        if cap is not None:
            others = sum(a[1] for a in active)
            room = max(0.0, cap / 100 - others)
            if room < r["f"]:
                scale = room / r["f"]
                bind += r["filled"]
        r["scale"] = scale
        active.append((r["end"], r["f"] * scale))
    throttled = 0
    if bucket_mode:
        fills = sorted((r for r in rows if r["filled"] and r["bucket"]), key=lambda r: r["entry"])
        for r in fills:
            first = [o for o in fills if o is not r and o["bucket"] == r["bucket"] and o["asset"] != r["asset"]
                     and o["side"] == r["side"] and o["entry"] < r["entry"] and o["end"] > r["entry"]
                     and o["entry"].date() == r["entry"].date()]
            if first:
                r["scale"] *= 0.5 if bucket_mode == "half" else 0.0
                throttled += 1
    trades = sorted((r for r in rows if r["filled"]), key=lambda r: r["end"])
    rets = [r["f"] * r["scale"] * r["R"] for r in trades]
    return trades, rets, bind, throttled


def stats(rets, label, months):
    eq = 1.0
    path = []
    for x in rets:
        eq *= 1 + x
        path.append(eq)
    mdd = cm.max_drawdown(rets)
    rng = random.Random(20261106)
    blocks = [rets[i:i + 10] for i in range(len(rets) - 9)]
    dds, terms = [], []
    for _ in range(5000):
        seq = []
        while len(seq) < len(rets):
            seq += blocks[rng.randrange(len(blocks))]
        e = pk = 1.0
        dd = 0.0
        for x in seq[:len(rets)]:
            e *= 1 + x
            pk = max(pk, e)
            dd = max(dd, 1 - e / pk)
        dds.append(dd)
        terms.append(e)
    dds.sort()
    terms.sort()
    return dict(label=label, trades=len(rets), terminal=eq, ann=eq ** (12 / months) - 1, maxdd=mdd,
                mc2_p50dd=dds[2500], mc2_p95dd=dds[4750], mc2_med_term=terms[2500], mc2_p5_term=terms[250],
                ruin=sum(1 for t in terms if t <= 0.5) / 5000, ret_dd=(eq - 1) / mdd if mdd else None)


def correlations(rows):
    daily = {}
    for r in rows:
        if r["filled"]:
            d = daily.setdefault(r["asset"], {})
            day = r["entry"].date()
            d[day] = d.get(day, 0.0) + r["R"]
    keys = sorted(daily)
    out = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            days = sorted(set(daily[a]) & set(daily[b]))
            if len(days) < 8:
                continue
            x, y = [daily[a][d] for d in days], [daily[b][d] for d in days]
            mx, my = st.mean(x), st.mean(y)
            sx, sy = sum((v - mx) ** 2 for v in x) ** 0.5, sum((v - my) ** 2 for v in y) ** 0.5
            if sx and sy:
                out[f"{a}~{b}"] = (len(days), sum((x[k] - mx) * (y[k] - my) for k in range(len(x))) / (sx * sy))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--streams", default=os.path.join(HERE, "aos_portfolio_streams.json"))
    ap.add_argument("--json")
    a = ap.parse_args()
    with open(a.streams, encoding="utf-8") as f:
        spec = json.load(f)
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(a.streams)), spec["runs_root"]))
    rows = []
    for key, s in spec["streams"].items():
        rows += load_stream(key, os.path.join(root, s["run_id"]), s.get("bucket", ""))
    days = sorted(r["arm"] for r in rows)
    months = (days[-1] - days[0]).days / 30.44
    print(f"streams {len(spec['streams'])}, armed setup-days {len(rows)}, fills {sum(r['filled'] for r in rows)}, "
          f"{days[0]:%Y-%m-%d} .. {days[-1]:%Y-%m-%d}")
    results = []
    variants = [("no portfolio rule", None, None)] + [(f"heat cap {c} %", c, None) for c in (2, 3, 4)] + \
               [("EU bucket half", None, "half"), ("EU bucket skip", None, "skip"), ("heat cap 3 % + EU bucket half", 3, "half")]
    print(f"\n  {'variant':30} {'trades':>6} {'terminal':>8} {'ann.':>7} {'MaxDD':>6} {'ret/DD':>6} {'MC2 P50DD':>9} "
          f"{'MC2 P95DD':>9} {'MC2 P5term':>10} {'ruin':>5} {'cap binds':>9} {'throttled':>9}")
    for label, cap, mode in variants:
        rr = [dict(r) for r in rows]
        trades, rets, bind, thr = replay(rr, cap, mode)
        s = stats(rets, label, months)
        s.update(cap_binds=bind, throttled=thr)
        results.append(s)
        print(f"  {label:30} {s['trades']:6} {s['terminal']:8.3f} {100 * s['ann']:6.1f}% {100 * s['maxdd']:5.1f}% "
              f"{s['ret_dd']:6.2f} {100 * s['mc2_p50dd']:8.1f}% {100 * s['mc2_p95dd']:8.1f}% {s['mc2_p5_term']:10.3f} "
              f"{100 * s['ruin']:4.1f}% {bind:9} {thr:9}")
    print("\n  daily-R correlation (shared days):")
    for k, (n, rho) in sorted(correlations(rows).items(), key=lambda kv: -abs(kv[1][1])):
        print(f"    {k:32} n={n:3}  rho={rho:+.2f}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
