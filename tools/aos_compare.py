"""AOS-P0-T04: compare an AI OS variant run with its baseline run, event by event (doc/ai_OS.md §3).

Both runs must use the same symbol, window and deposit; only AOS inputs may differ.

Usage:
  python aos_compare.py --pair BASE_RUN_DIR VARIANT_RUN_DIR [--pair ...] [--control BASE VARIANT ...] [--json out.json]
"""
import argparse
import csv
import json
import os

import corb_metrics as cm
from corb_bench import load_run

RESIZE_TOL = 0.15     # volume ratio outside 1 ± 15 % counts as resized
OUTCOME_TOL = 0.02    # |ΔR| above this on a shared event = engine outcome changed
FIRE_RETENTION = 0.70
EF_SLACK = 0.01       # EF may drop by 1 pp
DD_SLACK = 2.0        # equity MaxDD may rise by 2 pp
E_HOLD = 0.02         # "held" expectancy band, R


def _equity_dd_pct(events, deposit):
    eq = pk = deposit
    dd = 0.0
    for e in events:
        if e.get("pnl_ccy_est") not in (None, ""):
            eq += float(e["pnl_ccy_est"])
            pk = max(pk, eq)
            dd = max(dd, 1 - eq / pk)
    return 100 * dd


def _health(events, deposit):
    rs = [e["pnl_R"] for e in events]
    c = cm.core(rs) if rs else dict(n=0)
    if not rs or c.get("R") is None:
        return dict(n=len(rs), E=c.get("E"), E_N=None, WR=c.get("WR"), R=None, AL=None, EF=None, worst=None,
                    maxdd_R=None, maxdd_pct=None)
    leak = cm.leak(sum(e["c_slip_R"] for e in events) / len(rs), c["R"])
    return dict(n=c["n"], WR=c["WR"], R=c["R"], AL=c["AL"], E=c["E"], E_N=c["E_N"], EF=c["BM"] - leak,
                worst=min(rs), maxdd_R=cm.max_drawdown_r(rs), maxdd_pct=_equity_dd_pct(events, deposit))


def _subset(rs):
    if not rs:
        return dict(n=0, mean_R=None, sum_R=0.0, BM=None)
    c = cm.core(rs)
    return dict(n=len(rs), mean_R=sum(rs) / len(rs), sum_R=sum(rs), BM=c["BM"])


def compare(base_meta, base_events, var_meta, var_events, var_mult=None):
    """var_mult: {event_id: aos_mult} from the variant's ledger_decisions.csv. When given, a resize is a policy
    multiplier < 1; without it, volume ratios are used (they also catch compounding drift)."""
    b = {e["event_id"]: e for e in base_events}
    v = {e["event_id"]: e for e in var_events}
    withheld = [b[k]["pnl_R"] for k in b if k not in v]
    added = [k for k in v if k not in b]
    shared = [k for k in b if k in v]
    resized_down, resized_up, changed, switched, guard_exits, drift = [], [], [], [], [], 0
    for k in shared:
        ratio = float(v[k]["volume"]) / float(b[k]["volume"])
        if var_mult is not None:
            if var_mult.get(k, 1.0) < 1.0:
                resized_down.append(b[k]["pnl_R"])
            elif abs(ratio - 1) > 1e-9:
                drift += 1
        elif ratio < 1 - RESIZE_TOL:
            resized_down.append(b[k]["pnl_R"])
        elif ratio > 1 + RESIZE_TOL:
            resized_up.append(b[k]["pnl_R"])
        if v[k].get("side") != b[k].get("side"):
            switched.append(k)          # side gate withheld the first side; the other side filled later that day
        elif v[k].get("close_reason") == "SLIP_ABORT":
            guard_exits.append(k)       # L3 slippage abort closed the position on purpose
        elif abs(v[k]["pnl_R"] - b[k]["pnl_R"]) > OUTCOME_TOL:
            changed.append(k)
    hb = _health(base_events, base_meta["deposit"])
    hv = _health(var_events, var_meta["deposit"])
    # size-weighted R: each kept event's R scaled by variant / baseline volume (size layers move this, not E)
    w_r = [v[k]["pnl_R"] * float(v[k]["volume"]) / float(b[k]["volume"]) for k in shared]
    weighted = dict(sum_base=sum(e["pnl_R"] for e in base_events), sum_variant=sum(w_r),
                    mean_variant=sum(w_r) / len(w_r) if w_r else None)
    sw, sr = _subset(withheld), _subset(resized_down)
    retention = hv["n"] / hb["n"] if hb["n"] else 0.0
    d = lambda k: None if hb.get(k) is None or hv.get(k) is None else hv[k] - hb[k]

    checks = {}
    if hv["E_N"] is not None:
        improved_risk = hv["AL"] < hb["AL"] or hv["worst"] > hb["worst"] or hv["maxdd_pct"] < hb["maxdd_pct"]
        held = abs(hv["E"] - hb["E"]) <= E_HOLD and improved_risk
        size_only = not withheld and not guard_exits and not switched and not changed
        # a size-only layer cannot move R per event, so it must buy a real risk improvement in money terms
        checks["expectancy"] = (hv["maxdd_pct"] < hb["maxdd_pct"]) if size_only and sr["n"] else \
            (hv["E_N"] > hb["E_N"] or held or (hv["E_N"] == hb["E_N"] and not sr["n"]))
        checks["skip_precision"] = (sw["n"] == 0 or (sw["mean_R"] < 0 and (sw["BM"] is None or sw["BM"] <= 0))) and \
                                   (sr["n"] == 0 or sr["mean_R"] < hb["E"])
        checks["health_EF"] = hv["EF"] >= hb["EF"] - EF_SLACK
        checks["health_MaxDD"] = hv["maxdd_pct"] <= hb["maxdd_pct"] + DD_SLACK
    rejects = []
    for k in ("symbol", "deposit"):
        if base_meta.get(k) != var_meta.get(k):
            rejects.append(f"not comparable: {k} {base_meta.get(k)} vs {var_meta.get(k)} "
                           f"(lot minimum changes which days trade, CO-FX-03)")
    if hv["WR"] is not None and hb["WR"] is not None and hv["WR"] > hb["WR"] and \
            ((d("E_N") or 0) < 0 or (d("EF") or 0) < 0):
        rejects.append("payoff trap: WR up, E_N or EF down")
    if added:
        rejects.append(f"{len(added)} events not in baseline (layer must only withhold / resize)")
    if changed:
        rejects.append(f"{len(changed)} shared events changed outcome (engine not frozen)")
    warnings = []
    if retention < FIRE_RETENTION:
        warnings.append(f"FREQUENCY_STALL: fire retention {retention:.0%} < {FIRE_RETENTION:.0%}")
    if resized_up:
        warnings.append(f"{len(resized_up)} events sized up (> 1x not allowed before AOS-P7 R3)")
    verdict = "REJECT" if rejects else ("ACCEPT" if checks and all(checks.values()) else "NOT ACCEPTED")
    return dict(base=base_meta["run_id"], variant=var_meta["run_id"], symbol=base_meta["symbol"],
                health_base=hb, health_variant=hv, delta={k: d(k) for k in ("E", "E_N", "WR", "R", "AL", "EF", "worst",
                                                                             "maxdd_R", "maxdd_pct")},
                fire_retention=retention, withheld=sw, resized_down=sr, resized_up=len(resized_up), weighted=weighted,
                added=len(added), outcome_changed=len(changed), switched=dict(n=len(switched), base_R=sum(
                    b[k]["pnl_R"] for k in switched), variant_R=sum(v[k]["pnl_R"] for k in switched)),
                volume_drift=drift, guard_exits=dict(n=len(guard_exits), base_R=sum(b[k]["pnl_R"] for k in guard_exits),
                                                     variant_R=sum(v[k]["pnl_R"] for k in guard_exits)),
                checks=checks, rejects=rejects, warnings=warnings,
                verdict=verdict)


def pooled(results, controls):
    out = dict(pairs=len(results))
    out["improved"] = sum(1 for r in results if (r["delta"]["E_N"] or 0) >= 0)
    out["worst_asset_dE"] = min((r["delta"]["E"] or 0) for r in results) if results else 0.0
    out["breadth_ok"] = (out["improved"] >= min(4, len(results))) and out["worst_asset_dE"] >= -0.05
    # controls must stay Negative after costs (EF <= 0); raw E can sit a hair above 0 (MSFT baseline +0.02R, EF -2 pp)
    out["controls_ok"] = all((c["health_variant"]["EF"] or 0) <= 0 for c in controls)
    out["verdict"] = "ACCEPT" if out["breadth_ok"] and out["controls_ok"] and \
        not any(r["verdict"] == "REJECT" for r in results) else "NOT ACCEPTED"
    return out


def _fmt(r):
    hb, hv = r["health_base"], r["health_variant"]
    f = lambda x, p=3: "-" if x is None else f"{x:+.{p}f}"
    sw = r["withheld"]
    lines = [f"{r['symbol']}: {r['base']}  ->  {r['variant']}",
             f"  n {hb['n']} -> {hv['n']} (retention {r['fire_retention']:.0%})  E {f(hb['E'])} -> {f(hv['E'])}  "
             f"E_N {f(hb['E_N'])} -> {f(hv['E_N'])}  AL {f(hb['AL'], 2)} -> {f(hv['AL'], 2)}  "
             f"EF {f(hb['EF'] and 100 * hb['EF'], 1)} -> {f(hv['EF'] and 100 * hv['EF'], 1)} pp  "
             f"MaxDD {f(hb['maxdd_pct'], 1)} -> {f(hv['maxdd_pct'], 1)} %",
             f"  withheld {sw['n']} (mean {f(sw['mean_R'])}R, sum {sw['sum_R']:+.2f}R, BM "
             f"{'-' if sw['BM'] is None else f'{100 * sw['BM']:+.1f}pp'})  resized-down {r['resized_down']['n']}  "
             f"added {r['added']}  changed {r['outcome_changed']}  side-switched {r['switched']['n']} "
             f"({r['switched']['base_R']:+.2f}R -> {r['switched']['variant_R']:+.2f}R)  guard exits {r['guard_exits']['n']} "
             f"({r['guard_exits']['base_R']:+.2f}R -> {r['guard_exits']['variant_R']:+.2f}R)  volume drift {r['volume_drift']}  "
             f"size-weighted sum R {r['weighted']['sum_base']:+.2f} -> {r['weighted']['sum_variant']:+.2f}",
             f"  checks {r['checks']}", f"  verdict {r['verdict']}" + "".join(f"\n  REJECT: {x}" for x in r["rejects"])
             + "".join(f"\n  WARN: {x}" for x in r["warnings"])]
    return "\n".join(lines)


def _ledger_mult(run_dir):
    path = os.path.join(run_dir, "ledger_decisions.csv")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return {r["event_id"]: float(r["aos_mult"] or 1.0) for r in csv.DictReader(f) if "aos_mult" in r}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", nargs=2, action="append", default=[], metavar=("BASE", "VARIANT"))
    ap.add_argument("--control", nargs=2, action="append", default=[], metavar=("BASE", "VARIANT"),
                    help="negative-control pair (AAPL / MSFT / XOM): the variant must stay Negative (EF <= 0)")
    ap.add_argument("--json", help="write the full result here")
    a = ap.parse_args()
    if not a.pair:
        ap.error("at least one --pair")
    results = [compare(*load_run(p[0]), *load_run(p[1]), var_mult=_ledger_mult(p[1])) for p in a.pair]
    controls = [compare(*load_run(p[0]), *load_run(p[1]), var_mult=_ledger_mult(p[1])) for p in a.control]
    for r in results + controls:
        print(_fmt(r) + "\n")
    pool = pooled(results, controls)
    print(f"POOLED: improved {pool['improved']}/{pool['pairs']}, worst asset dE {pool['worst_asset_dE']:+.3f}R, "
          f"breadth_ok {pool['breadth_ok']}, controls_ok {pool['controls_ok']} -> {pool['verdict']}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(dict(pairs=results, controls=controls, pooled=pool), f, indent=1)


if __name__ == "__main__":
    main()
