"""CycleORB infra CLI (doc/infrascaleup.md). Run from tools/:  python -m corb <command>

  inventory [--no-external]   INF-P0-T02  hash every evidence file -> infra/inventory.json
  baseline lock               INF-P0-T03  recompute + verify the baseline -> infra/baseline_lock.json
  baseline check              INF-P0-T03  recompute and diff against the committed lock (no write)
  sources check               INF-P0-T04  check infra/sources.json, measure broker history depth

Every command writes a scorecard to var/scorecards/ (also latest.json and index.json).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corb import scorecard  # noqa: E402
from corb.paths import INFRA, portable  # noqa: E402


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")


def cmd_inventory(a):
    from corb import inventory
    inv = inventory.build(external=not a.no_external)
    out = os.path.join(INFRA, "inventory.json")
    _dump(out, inv)
    s = inv["summary"]
    print(f"{s['files']} files, {s['bytes'] / 1e6:.1f} MB, {s['runs']} run folders")
    print("kinds: " + ", ".join(f"{k} {v}" for k, v in s["kinds"].items()))
    print(f"duplicate file groups {s['duplicate_file_groups']}, runs sharing identical events {s['same_events_groups']}")
    for g in inv["duplicates"]["same_events"]:
        print("  same events: " + "  ==  ".join(g["run_ids"]))
    card = scorecard.write("INF-P0-T02_data_inventory", "ACCEPT", dict(summary=s, git=inv["git"],
                                                                       artefact=portable(out)))
    print("wrote", portable(out), "and", portable(card))


def _print_checks(checks):
    bad = [c for c in checks if not c["ok"]]
    print(f"{len(checks) - len(bad)} / {len(checks)} checks pass")
    for c in bad:
        print(f"  FAIL {c['name']}: expected {c['expected']} got {c['got']} (tol {c['tol']})")
    return bad


def cmd_baseline(a):
    from corb import baseline
    lock, checks = baseline.build()
    if a.action == "check":
        checks = baseline.diff_against_lock(lock)
    bad = _print_checks(checks)
    verdict = "REJECT" if bad else "ACCEPT"
    p = lock["pooled"]
    print(f"pooled full n={p['full']['n']} E={p['full']['E']:+.3f}R EF={100 * p['full']['EF']:+.1f}pp "
          f"M={100 * p['full']['M']:.1f}pp | W250 EF={100 * p['W250']['EF']:+.1f}pp | "
          f"W500 EF={100 * p['W500']['EF']:+.1f}pp")
    for k, r in lock["primary"].items():
        print(f"  {k:15} n={r['n']:3} E={r['E']:+.3f} EF={100 * r['EF']:+5.1f} M={100 * r['M']:4.1f} "
              f"MaxDD={r['maxdd_pct']:5.1f}% fires/90d={r['fires_90d']:5.1f} warn<{r['fires_warn_90d']:5.1f} "
              f"stall<{r['fires_stall_90d']:5.1f} armed/90d={r['armed_90d']:5.1f} {r['lifecycle']}")
    if a.action == "lock" and not bad:
        _dump(baseline.LOCK, lock)
        print("wrote", portable(baseline.LOCK))
    elif a.action == "lock":
        print("lock NOT written: fix the failing checks first (runbook: data -> execution -> regime -> structure)")
    card = scorecard.write(baseline.RECIPE if a.action == "lock" else "INF-P0-T03_train_baselineCheck", verdict,
                           dict(checks_total=len(checks), failures=bad, pooled=p,
                                artefact=portable(baseline.LOCK)))
    print("scorecard", portable(card))
    return 1 if bad else 0


def cmd_sources(a):
    from corb import sources
    res = sources.check()
    for r in res["sources"]:
        print(f"  {r['id']:28} {r['status']:12} {r['files']:4} files {r['bytes'] / 1e6:7.1f} MB")
    print("broker history (real ticks first..last month | M1 years):")
    for s, d in res["broker_depth"].items():
        yrs = d["m1_years"]
        print(f"  {s:10} ticks {d['ticks_from']}..{d['ticks_to']} ({d['tick_months']} mo) | "
              f"M1 {yrs[0] if yrs else '-'}..{yrs[-1] if yrs else '-'} ({len(yrs)} years)")
    print("ouroboros: " + ", ".join(f"{s['id']}={s['status']}" for s in res["ouroboros"]["slices"]))
    for item in res["open"]:
        print("  OPEN", item)
    card = scorecard.write(sources.RECIPE, res["verdict"], res)
    print("verdict", res["verdict"], "| scorecard", portable(card))


def main():
    ap = argparse.ArgumentParser(prog="corb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--no-external", action="store_true", help="skip Common\\Files and Tester\\logs")
    p.set_defaults(fn=cmd_inventory)
    p = sub.add_parser("baseline")
    p.add_argument("action", choices=["lock", "check"])
    p.set_defaults(fn=cmd_baseline)
    p = sub.add_parser("sources")
    p.add_argument("action", choices=["check"])
    p.set_defaults(fn=cmd_sources)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
