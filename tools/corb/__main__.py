"""CycleORB infra CLI (doc/infrascaleup.md). Run from tools/:  python -m corb <command>

  inventory [--no-external]   INF-P0-T02  hash every evidence file -> infra/inventory.json
  baseline lock               INF-P0-T03  recompute + verify the baseline -> infra/baseline_lock.json
  baseline check              INF-P0-T03  recompute and diff against the committed lock (no write)
  sources check [--freeze]    INF-P0-T04  check infra/sources.json, measure broker history depth;
                                          --freeze records the sha256 of the located Ouroboros slices

  contract build | ddl        INF-P1-T01  adapt + validate every run folder -> var/contract/*.csv | print DDL
  land runs | verify          INF-P1-T05  land run folders + tape (write-once, by sha256) | re-hash landed files
  db up | migrate             INF-P1-T02  start Postgres (docker compose) | apply migrations (dbmate)
  db migrate-check            INF-P1-T02  up / down / up on a scratch DB, compare with infra/db/schema.sql
  db load | check [--reload]  INF-P1-T04  full reload of core | rebuild R from legs, CO-FX from SQL, fingerprint

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
    with open(sources.SOURCES, encoding="utf-8") as f:
        spec = json.load(f)
    res = sources.check(spec, freeze=a.freeze)
    if a.freeze:
        sources.save(spec)
        print("froze sha256 of the located Ouroboros slices in", portable(sources.SOURCES))
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


def cmd_contract(a):
    from corb import contract
    from corb.paths import RUNS, VAR
    if a.action == "ddl":
        print(contract.ddl())
        return 0
    counts, violations = contract.build_all(RUNS, os.path.join(VAR, "contract"))
    total = sum(len(v) for v in violations.values())
    print("rows: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for name, v in violations.items():
        for i, field, problem in v[:10]:
            print(f"  {name}[{i}] {field}: {problem}")
    verdict = "ACCEPT" if total == 0 else "REJECT"
    print(f"{total} contract violations -> {verdict}")
    scorecard.write("INF-P1-T01_data_contractValidate_allRuns", verdict, dict(
        rows=counts, violations=total, first=[dict(resource=k, row=i, field=f, problem=p)
                                              for k, v in violations.items() for i, f, p in v[:20]]))
    return 0 if total == 0 else 1


def cmd_land(a):
    from corb import landing
    from corb.paths import RUNS, REPO
    if a.action == "runs":
        files = [os.path.join(d, f) for d, _, fs in os.walk(RUNS) for f in sorted(fs)]
        files.append(os.path.join(REPO, "tester", "aos", "tape", "tape_P1obs.csv"))
        res = landing.land(files, "repo")
        print(f"landed {res['landed']} new files, {res['duplicates']} duplicates (already landed by content)")
    bad = landing.verify()
    for b in bad:
        print(f"  {b['problem'].upper()} {b['path']}")
    verdict = "REJECT" if bad else "ACCEPT"
    print(f"landing verify: {len(bad)} problems -> {verdict}")
    scorecard.write("INF-P1-T05_data_landingVerify", verdict, dict(problems=bad))
    return 1 if bad else 0


def cmd_db(a):
    from corb import contract, db, landing
    from corb.paths import RUNS, VAR
    if a.action == "up":
        db.up()
        print("db up (healthy)")
    elif a.action == "migrate":
        print(db.migrate().strip() or "migrations applied")
    elif a.action == "migrate-check":
        res = db.migrate_check(write_snapshot=a.write_snapshot)
        print(res)
        verdict = "ACCEPT" if all(res.values()) else "REJECT"
        scorecard.write("INF-P1-T02_store_migrationUpDownUp", verdict, res)
        return 0 if verdict == "ACCEPT" else 1
    elif a.action == "load":
        counts, violations = contract.build_all(RUNS, os.path.join(VAR, "contract"))
        if any(violations.values()):
            print("contract violations: run `python -m corb contract build` and fix them first")
            return 1
        landing.export_source_files()
        db.load()
        print("loaded: " + ", ".join(f"{k} {v}" for k, v in db.table_counts().items()))
    elif a.action == "check":
        checks, fp = db.check(reload=a.reload)
        bad = _print_checks(checks)
        verdict = "REJECT" if bad else "ACCEPT"
        print(f"event fingerprint {fp} -> {verdict}")
        scorecard.write("INF-P1-T04_store_rebuildEvents_allRuns", verdict, dict(
            checks_total=len(checks), failures=bad, fingerprint=fp))
        return 1 if bad else 0
    return 0


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
    p.add_argument("--freeze", action="store_true", help="record the sha256 of every located Ouroboros slice")
    p.set_defaults(fn=cmd_sources)
    p = sub.add_parser("contract")
    p.add_argument("action", choices=["build", "ddl"])
    p.set_defaults(fn=cmd_contract)
    p = sub.add_parser("land")
    p.add_argument("action", choices=["runs", "verify"])
    p.set_defaults(fn=cmd_land)
    p = sub.add_parser("db")
    p.add_argument("action", choices=["up", "migrate", "migrate-check", "load", "check"])
    p.add_argument("--write-snapshot", action="store_true", help="migrate-check: rewrite infra/db/schema.sql")
    p.add_argument("--reload", action="store_true", help="check: reload and compare the event fingerprint")
    p.set_defaults(fn=cmd_db)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
