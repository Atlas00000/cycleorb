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

  ingest                      INF-P2-T01  land everything new, load only new / changed runs (incl. live VPS months)
  dq                          INF-P2-T03/T06  ledger vs journal + data-quality checks -> ops.dq_result; cost sources
  replay <journal> --version  INF-P2-T05  re-parse a raw journal; baselines must be byte- and number-identical
  import ouroboros            INF-P2-T08  land the frozen Ouroboros slices (refused if a hash moved)
  tester exp | build          INF-P2-T04  EXP presets + inis | build the Wine + MT5 tester image
  tester run [inis] | parity  INF-P2-T04  run tester containers (login from infra/.env) | compare with native runs
  features registry | audit   INF-P3-T01 / T04  feature registry -> DB | point-in-time audit of the EA features
  features tape | cells       INF-P3-T05 / T06  regime tape per evaluated day | BM per regime cell (actual + shadow)
  bars prepare | export | lake  INF-P3-T02  portable MT5 copy | headless offline bar export | parquet lake + index
  train regression            INF-P4-T01  the harness reproduces the recorded AOS-P4 / AOS-P2 results
  train folds [--embargo N]   INF-P4-T02  walk-forward folds + decay guard
  train run [--family X]      INF-P4-T03..T06  shadow L2 (engine | cell_rule | ridge_logit | gbt | all) -> verdict
  ops journals | why <event>  INF-P5-T01  journal lines -> raw.journal_line | every journal line of one setup-day
  ops reasons | metrics       INF-P5-T03 / T02  reason-code catalogue | operational metrics -> ops.metric
  ops roles                   INF-P5-T06  DB roles + permission checks + git-history secret scan
  jobs enqueue <cmd> | work   INF-P5-T05  Postgres job queue (SKIP LOCKED) and a worker
  test lint | golden | image | replay | all   INF-P5-T04 / T07  presets, golden hash, job image, host = container

Every command writes a scorecard to var/scorecards/ (also latest.json and index.json).
"""
import argparse
import glob
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


def cmd_ingest(a):
    from corb import ingest
    res = ingest.ingest()
    print(f"runs seen {res['runs_seen']} (live {res['live_runs']}): loaded {res['runs_loaded']}, "
          f"unchanged {res['runs_unchanged']}, rejected {len(res['rejected'])}")
    print("landed: " + ", ".join(f"{o} {r['landed']} new / {r['duplicates']} dup" for o, r in res["landed"].items()))
    print(f"rows written: {sum(res['rows_staged'].values())} | new source files: {res['source_files_inserted']}")
    for r in res["rejected"]:
        print(f"  REJECTED {r['run']}: {r['problem']}")
    verdict = "REJECT" if res["rejected"] else "ACCEPT"
    scorecard.write("INF-P2-T01_data_ingest", verdict, res)
    return 1 if res["rejected"] else 0


def cmd_dq(a):
    from corb import dq
    summary, failures = dq.run_checks()
    checks = sorted({c for c, _ in summary})
    for c in checks:
        print(f"  {c:32} pass {summary[(c, 'pass')]:3}  warn {summary[(c, 'warn')]:3}  fail {summary[(c, 'fail')]:3}")
    for f in failures:
        print(f"  FAIL {f['check']} {f['run']}: {f['value']} {f['detail'][:160]}")
    costs = dq.cost_sources()
    print("cost sources (baseline runs): " + "; ".join(
        f"{k} ledger {v['money_from_ledger']:.0%} Leak {100 * v['leak_db']:.2f}pp "
        f"{'=' if v['leak_match'] else '!='} frozen" for k, v in costs.items()))
    bad = failures or [k for k, v in costs.items() if not v["leak_match"]]
    verdict = "REJECT" if bad else "ACCEPT"
    print("verdict", verdict)
    scorecard.write("INF-P2-T06_data_qualityChecks", verdict, dict(
        summary={f"{c}|{s}": n for (c, s), n in summary.items()}, failures=failures, cost_sources=costs))
    return 1 if bad else 0


def cmd_replay(a):
    from corb import replay
    info, checks = replay.replay(a.journal, a.version)
    print(f"parsed {info['runs_parsed']} runs into {portable(info['out'])}; baselines found: {info['baselines_found']}")
    bad = _print_checks(checks)
    verdict = "REJECT" if bad or not info["baselines_found"] else "ACCEPT"
    print("verdict", verdict)
    name = os.path.splitext(os.path.basename(a.journal))[0]
    scorecard.write(f"INF-P2-T05_data_replayJournal_{name}", verdict, dict(info, checks_total=len(checks), failures=bad))
    return 1 if verdict == "REJECT" else 0


def cmd_import(a):
    from corb import ingest
    res = ingest.import_ouroboros()
    for r in res:
        print(f"  {r['id']:24} {r['status']}")
    refused = [r for r in res if r["status"].startswith("refused")]
    verdict = "REJECT" if refused else "ACCEPT"
    print(f"{sum(r['status'] == 'landed' for r in res)} landed, "
          f"{sum(r['status'] == 'duplicate' for r in res)} duplicates, {len(refused)} refused -> {verdict}")
    scorecard.write("INF-P2-T08_data_importOuroboros", verdict, dict(slices=res))
    return 1 if refused else 0


def cmd_tester(a):
    from corb import tester
    if a.action == "exp":
        print("wrote: " + ", ".join(tester.make_exp()))
        return 0
    if a.action == "build":
        info = tester.build()
        print(info)
        scorecard.write("INF-P2-T04_box_testerImageBuild", "ACCEPT", info)
        return 0
    if a.action == "run":
        inis = a.inis or sorted(glob.glob(os.path.join(tester.EXP_INIS, "*.ini")))
        for r in tester.run(inis, parallel=a.parallel, timeout=a.timeout):
            print(f"  {r['name']}: exit {r['exit']}, attempts {r['attempts']}, journals {r['journals']}, "
                  f"parsed runs {r['runs']}")
    checks = tester.parity()
    bad = _print_checks(checks)
    verdict = "REJECT" if bad else "ACCEPT"
    print("parity", verdict)
    scorecard.write("INF-P2-T04_box_testerContainerParity_allAssets", verdict,
                    dict(checks_total=len(checks), failures=bad))
    return 1 if bad else 0


def cmd_features(a):
    from corb import regime
    if a.action == "registry":
        res = regime.registry()
        bad = res["not_in_adapter"] + res["adapter_not_registered"] + res["tape_features_not_registered"] + \
            res["stored_not_registered"]
        print(res)
        verdict = "REJECT" if bad else "ACCEPT"
        scorecard.write("INF-P3-T01_feat_registry", verdict, res)
    elif a.action == "audit":
        res = regime.audit()
        print(res)
        bad = res["as_of_after_decision"] or res["decided_after_fill"] or res["label_columns_in_features"]
        verdict = "REJECT" if bad else "HOLD"   # HOLD until the bar-based future-shift test exists (T03)
        scorecard.write("INF-P3-T04_feat_pitAudit", verdict, res)
    elif a.action == "build":
        from corb import featbuild
        per_asset, pooled = featbuild.run_all()
        for f, p in sorted(pooled.items(), key=lambda kv: kv[1]["share"]):
            print(f"  {f:18} {p['ok']:5}/{p['n']:5} ({100 * p['share']:5.1f}%) {p['status']}")
        fs = {k: v["future_shift"] for k, v in per_asset.items()}
        changed = sum(v["days_changed"] for v in fs.values())
        print(f"future-shift: {sum(v['days_checked'] for v in fs.values())} days rebuilt with every bar after the "
              f"range end deleted, {changed} changed")
        rejected = [f for f, p in pooled.items() if p["status"] == "reject"]
        verdict = "REJECT" if rejected or changed else "ACCEPT"
        scorecard.write("INF-P3-T03_feat_offlineParity_P1obs", "REJECT" if rejected else "ACCEPT",
                        dict(pooled=pooled, per_asset={k: {kk: vv for kk, vv in v.items() if kk != "parity"}
                                                       for k, v in per_asset.items()},
                             catalogued=[f for f, p in pooled.items() if p["status"] == "catalogued"]))
        audit = regime.audit()
        audit["future_shift_test"] = fs
        scorecard.write("INF-P3-T04_feat_pitAudit", "REJECT" if changed or audit["as_of_after_decision"]
                        or audit["decided_after_fill"] else "ACCEPT", audit)
    elif a.action == "tape":
        res = regime.build_tape()
        for k, v in res.items():
            print(f"  {k:15} days {v['days']:4}  with EA features {v['with_features']:4}  "
                  f"range/ATR cuts {v['cuts'][0]:.1f} / {v['cuts'][1]:.1f}")
        verdict = "ACCEPT"
        scorecard.write("INF-P3-T05_feat_regimeTape", verdict, dict(assets=res))
    else:
        res = regime.build_cells()
        bad = [c for c in res["checks"] if not c["ok"]]
        print(f"{res['cells']} cells; frozen-cell checks {len(res['checks']) - len(bad)} / {len(res['checks'])} pass")
        for c in bad:
            print(f"  FAIL {c['name']}: expected {c['expected']} got {c['got']}")
        for f in res["flagged"]:
            print(f"  BM <= 0: {f['asset']:15} ({f['role']}) {f['dim']}={f['value']:8} n={f['n']:3} "
                  f"actual {100 * f['bm_actual']:+.1f}pp shadow "
                  f"{'-' if f['bm_shadow'] is None else f'{100 * f['bm_shadow']:+.1f}pp'} both={f['both_streams']}")
        verdict = "REJECT" if bad else "ACCEPT"
        scorecard.write("INF-P3-T06_feat_cellBM", verdict, res)
    print("verdict", verdict)
    return 1 if verdict == "REJECT" else 0


def cmd_bars(a):
    from corb import bars
    res = getattr(bars, a.action)()
    shown = {k: v for k, v in res.items() if k != "manifest"}
    print(shown)
    if a.action == "export":
        for r in res["manifest"]:
            if r["tf"] == "M1":
                print(f"  {r['symbol']:10} M1 {r['year']}: {int(r['rows']):7} bars {r['first']} .. {r['last']}")
    verdict = "ACCEPT" if (a.action != "export" or res["bars"] > 0) and (a.action != "prepare" or res["compiled"]) \
        else "REJECT"
    scorecard.write(f"INF-P3-T02_feat_bars{a.action.capitalize()}", verdict, shown)
    print("verdict", verdict)
    return 0 if verdict == "ACCEPT" else 1


def cmd_train(a):
    from corb import evaluate as ev
    if a.action == "regression":
        res = ev.regression()
        bad = [r for r in res if not r["ok"]]
        print(f"{len(res) - len(bad)} / {len(res)} recorded results reproduced")
        for r in bad:
            print(f"  FAIL {r['name']}: expected {r['expected']} got {r['got']}")
        verdict = "REJECT" if bad else "ACCEPT"
        scorecard.write("INF-P4-T01_train_harnessRegression_AOS-P2-P4", verdict, dict(checks=res))
        print("verdict", verdict)
        return 1 if bad else 0
    if a.action == "folds":
        df = ev.load()
        fl = ev.folds(df, embargo_days=a.embargo)
        decay_only = df[(df.asset == "DE40") & (df.month >= "2026-09")]
        res = dict(folds=len(fl), months=[f[0] for f in fl], train_sizes=[len(f[1]) for f in fl],
                   test_sizes=[len(f[2]) for f in fl], embargo_days=a.embargo,
                   guard_refuses_decay_only=not ev.decay_guard_ok(decay_only),
                   guard_accepts_anchored=all(ev.decay_guard_ok(df.loc[f[1]]) for f in fl))
        print(res)
        ok = res["guard_refuses_decay_only"] and res["guard_accepts_anchored"] and res["folds"] > 0
        scorecard.write("INF-P4-T02_train_folds", "ACCEPT" if ok else "REJECT", res)
        return 0 if ok else 1
    if a.action == "gain":
        res = ev.data_gain()
        print(f"replica rows (training only): {res['replica_rows']} {res['replica_by_asset']}; "
              f"OOS months {res['oos_months'][0]}..{res['oos_months'][-1]} (tester rows only)")
        f3 = lambda x: "-" if x is None else f"{x:+.3f}"
        for k, r in res["results"].items():
            print(f"  {k:28} {r['verdict']:13} train rows (fold 1) {r['train_rows_first_fold']:4}  skipped {r['withheld']:3}"
                  f"/{r['n_base']}  withheld mean {f3(r['withheld_mean'])}R  p_rand "
                  f"{'-' if r['p_rand'] is None else round(r['p_rand'], 2)}  E_N {f3(r['E_N'][0])} -> {f3(r['E_N'][1])}"
                  f"  {'; '.join(r['failed'] + r['rejects'])[:120]}")
        gained = [k for k, r in res["results"].items() if k.startswith("tester+replica") and r["verdict"] == "ACCEPT"]
        verdict = "ACCEPT" if gained else "NOT ACCEPTED"
        print("data gain:", gained or "no family passes with the extra history: the engine stays ungated")
        scorecard.write("INF-P4-T07_train_L2shadow_dataGain_replicaExt", verdict, res)
        return 0
    families = ev.FAMILIES if a.family == "all" else [a.family]
    worst = 0
    for fam in families:
        res = ev.run(fam, embargo_days=a.embargo)
        p = res["pooled"]
        f3 = lambda x: "-" if x is None else f"{x:+.3f}"
        print(f"== {fam}: {res['verdict']}  folds {res['folds']} ({res['oos_months'][0]}..{res['oos_months'][-1]})"
              f"  skipped {p['withheld']} of {p['n_base']} asset days"
              f"  withheld mean {f3(p['withheld_mean'])}R  p_rand {p['p_rand'] if p['p_rand'] is None else round(p['p_rand'], 2)}")
        if p["kept"] and p["base"]:
            print(f"   pooled E {f3(p['base']['E'])} -> {f3(p['kept']['E'])}  E_N {f3(p['base']['E_N'])} -> "
                  f"{f3(p['kept']['E_N'])}  EF {100 * p['base']['EF']:+.1f} -> {100 * p['kept']['EF']:+.1f}pp  "
                  f"W250 EF {100 * p['W250']['base']:+.1f} -> {100 * p['W250']['kept']:+.1f}pp")
        for k, v in res["per_asset"].items():
            if v["withheld"]:
                print(f"   {k:15} skipped {v['withheld']:3}/{v['n_base']:3} (ret {v['retention']:.0%}) withheld mean "
                      f"{f3(v['withheld_mean'])}R  E {f3(v['base']['E'])} -> {f3(v['kept'] and v['kept']['E'])}")
        for c in res["checks"]:
            if not c["ok"]:
                print(f"   FAIL {c['name']} {c['detail']}")
        for r in res["rejects"] + res["warnings"]:
            print(f"   NOTE {r}")
        if res.get("note"):
            print(f"   {res['note']}")
        print(f"   registry: {res['registry']['model_semver']} ({res['registry']['status']}), eval {res['registry']['eval_id']}")
        scorecard.write(res["recipe"], res["verdict"], {k: v for k, v in res.items() if k not in ("recipe", "verdict")})
        worst = max(worst, res["verdict"] == "REJECT")
    return worst


def cmd_replica(a):
    from corb import replica
    if a.action == "parity":
        rows = replica.parity()
        g = replica.GATE
        for r in rows:
            print(f"  {r['asset']:15} {r['role']:7} events {r['native_n']:3} / {r['replica_n']:3}  set {r['event_set']:.1%}  "
                  f"pnl within {g['pnl_tol']}R {r['pnl_within']:.0%} (median diff {r['pnl_median_diff']:.4f}R)  "
                  f"EF {100 * r['EF_native']:+.1f} / {100 * r['EF_replica']:+.1f}pp  {'PASS' if r['pass'] else 'fail'}")
        crit = dict(event_set=sum(r["event_set"] >= g["event_set"] for r in rows),
                    pnl=sum(r["pnl_within"] >= g["pnl_share"] for r in rows),
                    EF=sum(r["EF_diff_pp"] is not None and r["EF_diff_pp"] <= g["ef_pp"] for r in rows),
                    controls_negative=sum(r["EF_replica"] <= 0 for r in rows if r["role"] == "control"))
        passed = [r["asset"] for r in rows if r["pass"]]
        print(f"assets passing each criterion (of {len(rows)}): {crit}; all criteria: {passed or 'none'}")
        verdict = "ACCEPT" if len(passed) == len(rows) else "NOT ACCEPTED"
        scorecard.write("INF-P3-T07_feat_replicaParity_2025-07_2026-10", verdict,
                        dict(gate=g, criteria_passed=crit, assets_passed=passed, assets=rows))
        return 0
    rows = []
    for asset in replica.EXTEND:
        r = replica.extend_asset(asset)
        if r:
            d, m = r
            rows.append(dict(asset=asset, run_id=m["run_id"], window=m["window"], months=len(m["months_used"]),
                             events=m["n_events"], armed_days=m["armed_days"]))
            print(f"  {asset:15} {m['window'][0]} .. {m['window'][1]}  {len(m['months_used']):2} clean months  "
                  f"{m['n_events']:4} events")
    scorecard.write("INF-P3-T07_feat_replicaExtend_preTester", "ACCEPT", dict(runs=rows))
    return 0


def cmd_prove(a):
    from corb import prove
    tag = lambda fam, data: f"{fam}_{'tape' if data == 'tester' else 'tapeReplica'}"
    f3 = lambda x: "-" if x is None else f"{x:+.3f}"
    decisions = []
    for fam, data in prove.CANDIDATES:
        r = s = None
        if a.action in ("report", "all"):
            r = prove.report(fam, data)
            p = r["pooled"]
            print(f"  T01 {tag(fam, data):24} primary {r['primary_verdict']:12} skips {r['skips']:3} "
                  f"({p['skip_rate']:.0%})  W250 EF {100 * p['W250_EF'][0]:+.1f} -> {100 * p['W250_EF'][1]:+.1f}pp  "
                  f"W500 EF {100 * (p['W500']['base_EF'] or 0):+.1f} -> {100 * (p['W500']['kept_EF'] or 0):+.1f}pp "
                  f"(n {p['W500']['n_base']})  withheld {f3(p['withheld_mean'])}R  portfolio MaxDD "
                  f"{100 * r['portfolio']['base']['maxdd']:.1f} -> {100 * r['portfolio']['kept']['maxdd']:.1f}%  "
                  f"secondary/portfolio fails {len(r['extra_failed'])}")
            scorecard.write(f"INF-P6-T01_L2shadow_{tag(fam, data)}", "ACCEPT" if r["gate_ok"] else "NOT ACCEPTED", r)
        if a.action in ("stability", "all"):
            s = prove.stability(fam, data)
            print(f"  T02 {tag(fam, data):24} base {s['base_verdict']:12} same verdict on {s['same_share']:.0%} of "
                  f"{len(s['variants'])} perturbations  accept anywhere: {s['any_accept'] or 'none'}  size-only E_N "
                  f"{f3(s['size_only']['E_N'][0])} -> {f3(s['size_only']['E_N'][1])}")
            scorecard.write(f"INF-P6-T02_L2shadow_{tag(fam, data)}", "ACCEPT" if s["stable"] else "REJECT", s)
        if r and s:
            ok = r["gate_ok"] and s["stable"] and s["base_verdict"] == "ACCEPT"
            decisions.append(dict(candidate=tag(fam, data), decision="PASS: INF-P7 unlocked" if ok else "SHELVED",
                                  primary=r["primary_verdict"], failed=r["primary_failed"] + r["extra_failed"],
                                  rejects=r["rejects"], stable_share=s["same_share"], accept_anywhere=s["any_accept"]))
    if decisions:
        passed = [d["candidate"] for d in decisions if d["decision"].startswith("PASS")]
        print("phase-prove:", passed or "no L2 candidate passes: the engine stays ungated, INF-P7 stays locked")
        scorecard.write("INF-P6-T01_train_phaseProve_L2shadow_W250-W500", "ACCEPT" if passed else "NOT ACCEPTED",
                        dict(decisions=decisions, passed=passed))
    return 0


def cmd_ops(a):
    from corb import ops
    if a.action == "why":
        for t, sym, ver, kind, msg in ops.why(a.arg):
            print(f"  {t}  {sym} v{ver}  {kind or '':8} {msg}")
        return 0
    if a.action == "journals":
        res = ops.load_journals()
        print(res)
        scorecard.write("INF-P5-T01_obs_journalLines", "ACCEPT", res)
    elif a.action == "reasons":
        res = ops.reason_codes()
        print(res)
        scorecard.write("INF-P5-T03_obs_reasonCodes", "REJECT" if res["uncatalogued"] else "ACCEPT", res)
    elif a.action == "metrics":
        rows = ops.collect()
        for r in rows:
            if r["status"] != "ok":
                print(f"  {r['status'].upper():5} {r['name']:26} {r['subject']:15} {r['value']}  {r['detail']}")
        n = {s: sum(r["status"] == s for r in rows) for s in ("ok", "warn", "alarm")}
        print(f"{len(rows)} metrics: {n}")
        scorecard.write("INF-P5-T02_obs_metrics", "ACCEPT", dict(counts=n, metrics=rows))
    elif a.action == "roles":
        checks = ops.roles()
        bad = [c for c in checks if not c["ok"]]
        for c in checks:
            print(f"  {'ok ' if c['ok'] else 'FAIL'} {c['name']}: allowed={c['got']} (expected {c['expected']})")
        scan = ops.secret_scan()
        print(scan)
        ok = not bad and not scan["found_in_history"] and not scan["env_tracked"]
        scorecard.write("INF-P5-T06_box_rolesAndSecrets", "ACCEPT" if ok else "REJECT", dict(checks=checks, scan=scan))
        return 0 if ok else 1
    elif a.action == "grafana":
        res = ops.grafana_up()
        print(f"grafana {res['url']}  datasource {res['datasource']} ({res['datasource_message']})")
        for p in res["panels"]:
            print(f"  {'ok ' if not p['error'] else 'ERR'} {p['rows']:4} rows  {p['title'][:70]}  {p['error'] or ''}")
        ok = res["datasource"] == "OK" and not any(p["error"] for p in res["panels"])
        scorecard.write("INF-P5-T02_obs_grafanaBoard", "ACCEPT" if ok else "REJECT", res)
        return 0 if ok else 1
    elif a.action == "grafana-down":
        ops.grafana_down()
    return 0


def cmd_test(a):
    import subprocess
    from corb import infratest as it
    results = {}
    if a.action in ("lint", "all"):
        r = it.preset_lint()
        for p in r["problems"]:
            print("  LINT", p)
        print(f"preset lint: {r['presets']} presets vs {r['ea_inputs']} EA inputs: {len(r['problems'])} problems, "
              f"{len(r['warnings'])} warnings")
        results["preset_lint"] = not r["problems"]
        scorecard.write("INF-P5-T07_test_presetLint_allPresets", "ACCEPT" if not r["problems"] else "REJECT", r)
    if a.action in ("golden", "all"):
        r = it.golden(update=a.update)
        print("golden health vectors:", r)
        results["golden"] = r["ok"]
    if a.action in ("image", "replay", "all"):
        image_id = it.build_image()
        print("job image", image_id[:19])
    if a.action in ("replay", "all"):
        rows = it.replay()
        for r in rows:
            print(f"  {r['command']:18} host {r['host_verdict']:12} container {r['container_verdict']:12} "
                  f"same={r['same']} {r['stderr']}")
        results["container_replay"] = all(r["same"] and r["host_exit"] == r["container_exit"] == 0 for r in rows)
        scorecard.write("INF-P5-T04_pack_crossMachineReplay", "ACCEPT" if results["container_replay"] else "REJECT",
                        dict(image=image_id, replays=rows))
    if a.action == "all":
        u = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], capture_output=True,
                           text=True)
        results["unit_tests"] = u.returncode == 0
        print("unit tests:", (u.stderr.strip().splitlines() or ["?"])[-1])
        from corb import db
        mc = db.migrate_check()
        results["migrations_up_down_up"] = all(mc.values())
        print("migrations:", mc)
        verdict = "ACCEPT" if all(results.values()) else "REJECT"
        print("test all:", results, "->", verdict)
        scorecard.write("INF-P5-T07_test_all", verdict, results)
        return 0 if verdict == "ACCEPT" else 1
    return 0 if all(results.values()) else 1


def cmd_jobs(a):
    from corb import ops
    if a.action == "enqueue":
        print("job", ops.enqueue(" ".join(a.command)))
        return 0
    for d in ops.work(once=a.once):
        print(f"  job {d['job_id']} {d['status']} in {d['seconds']} s: {d['command']}")
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
    p = sub.add_parser("ingest")
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("dq")
    p.set_defaults(fn=cmd_dq)
    p = sub.add_parser("replay")
    p.add_argument("journal")
    p.add_argument("--version", required=True, help="EA version of the runs to replay (e.g. 1.11)")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("import")
    p.add_argument("source", choices=["ouroboros"])
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("tester")
    p.add_argument("action", choices=["exp", "build", "run", "parity"])
    p.add_argument("inis", nargs="*", help="run: tester inis (default: every tester/exp/*.ini)")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--timeout", type=int, default=5400, help="seconds per job")
    p.set_defaults(fn=cmd_tester)
    p = sub.add_parser("features")
    p.add_argument("action", choices=["registry", "audit", "build", "tape", "cells"])
    p.set_defaults(fn=cmd_features)
    p = sub.add_parser("bars")
    p.add_argument("action", choices=["prepare", "export", "lake"])
    p.set_defaults(fn=cmd_bars)
    p = sub.add_parser("train")
    p.add_argument("action", choices=["regression", "folds", "run", "gain"])
    p.add_argument("--family", default="all", choices=["all", "engine", "cell_rule", "ridge_logit", "gbt"])
    p.add_argument("--embargo", type=int, default=0, help="days between training end and the test month")
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("prove")
    p.add_argument("action", choices=["report", "stability", "all"])
    p.set_defaults(fn=cmd_prove)
    p = sub.add_parser("replica")
    p.add_argument("action", choices=["parity", "extend"])
    p.set_defaults(fn=cmd_replica)
    p = sub.add_parser("ops")
    p.add_argument("action", choices=["journals", "reasons", "metrics", "roles", "why", "grafana", "grafana-down"])
    p.add_argument("arg", nargs="?", help="why: an event_id, e.g. 26110311-20250708")
    p.set_defaults(fn=cmd_ops)
    p = sub.add_parser("test")
    p.add_argument("action", choices=["lint", "golden", "image", "replay", "all"])
    p.add_argument("--update", action="store_true", help="golden: re-record the health-vector hash on purpose")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("jobs")
    p.add_argument("action", choices=["enqueue", "work"])
    p.add_argument("command", nargs="*", help="enqueue: a corb command, e.g. ingest")
    p.add_argument("--once", action="store_true", help="work: stop when the queue is empty")
    p.set_defaults(fn=cmd_jobs)
    a = ap.parse_args()
    import time
    from corb.ops import log
    job = a.cmd + ("." + a.action if getattr(a, "action", None) else "")
    t0 = time.time()
    log(job, msg="start", argv=sys.argv[1:])
    try:
        code = a.fn(a) or 0
    except Exception as e:
        log(job, level="error", msg="exception", error=f"{type(e).__name__}: {e}", seconds=round(time.time() - t0, 1))
        raise
    log(job, level="info" if code == 0 else "warn", msg="end", exit_code=code, seconds=round(time.time() - t0, 1))
    sys.exit(code)


if __name__ == "__main__":
    main()
