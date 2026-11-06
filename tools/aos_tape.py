"""AOS-P1-T07: ledger collection, P1 exit checks and the pooled feature tape.

  collect  copy Common\\Files\\CycleORB\\CORB_<base>_<symbol>_tester_<deposit>_<tag>_<kind>.csv into each tagged run folder
  check    P1 exit criteria per asset: zero-diff vs baseline, ledger == journal, shadow == actual (±0.02R), look-ahead audit
  build    pooled tape: one row per ARMED setup-day with L1 features, actual outcome and shadow outcome

Usage (from tools/):
  python aos_tape.py collect --tag P1obs
  python aos_tape.py check   --assets aos_assets.json --tag P1obs
  python aos_tape.py build   --assets aos_assets.json --tag P1obs --out ../tester/aos/tape/tape_P1obs.csv
"""
import argparse
import csv
import glob
import json
import os
import shutil
from datetime import datetime

from aos_compare import compare
from corb_bench import load_run

COMMON = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common", "Files", "CycleORB")
HERE = os.path.dirname(os.path.abspath(__file__))
SHADOW_TOL = 0.02


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _spec(path):
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), spec["runs_root"]))
    return spec, root


def tagged_dir(root, base_run_id, tag):
    """Folder of the tagged run for a baseline run, whatever EA version produced it (latest version wins)."""
    rest = base_run_id.split("_", 1)[1]
    hits = sorted(glob.glob(os.path.join(root, f"v*_{rest}_{tag}")))
    return hits[-1] if hits else os.path.join(root, f"{base_run_id}_{tag}")


def collect(runs_root, tag):
    n = 0
    for meta_path in glob.glob(os.path.join(runs_root, f"*_{tag}", "meta.json")):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        prefix = f"CORB_{meta['magic_base']}_{meta['symbol']}_tester_{int(meta['deposit'])}_{tag}_"
        for kind in ("decisions", "events", "shadow"):
            src = os.path.join(COMMON, prefix + kind + ".csv")
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(os.path.dirname(meta_path), f"ledger_{kind}.csv"))
                n += 1
            else:
                print(f"missing {src}")
        print(f"collected {meta['run_id']}")
    return n


def _t(s):
    return datetime.strptime(s, "%Y.%m.%d %H:%M:%S") if s else None


def check_asset(key, base_dir, obs_dir):
    out = dict(asset=key)
    bm, be = load_run(base_dir)
    om, oe = load_run(obs_dir)
    cmp = compare(bm, be, om, oe)
    out["zero_diff"] = cmp["withheld"]["n"] == 0 and cmp["added"] == 0 and cmp["outcome_changed"] == 0 \
        and cmp["resized_down"]["n"] == 0 and cmp["resized_up"] == 0
    out["n_base"], out["n_obs"] = cmp["health_base"]["n"], cmp["health_variant"]["n"]
    bv = {e["event_id"]: e["volume"] for e in be}
    out["volume_diffs"] = [k for k in (e["event_id"] for e in oe) if k in bv and bv[k] != dict(
        (x["event_id"], x["volume"]) for x in oe)[k]]
    out["final_base"], out["final_obs"] = bm["final"], om["final"]

    led = {r["event_id"]: r for r in _read_csv(os.path.join(obs_dir, "ledger_events.csv"))}
    jr = {e["event_id"]: e for e in oe}
    out["ledger_events"] = len(led)
    out["ledger_match"] = set(led) == set(jr) and all(abs(float(led[k]["pnl_R"]) - jr[k]["pnl_R"]) < 1e-5 for k in jr)

    shadow = {r["event_id"]: r for r in _read_csv(os.path.join(obs_dir, "ledger_shadow.csv"))}
    diffs, missing = [], 0
    for k, e in jr.items():
        s = shadow.get(k)
        if not s or s["status"] != "FILLED" or not s["shadow_R"]:
            missing += 1
            continue
        diffs.append(abs(float(s["shadow_R"]) - e["pnl_R"]))
    out["shadow_rows"] = len(shadow)
    out["shadow_missing"] = missing
    out["shadow_within_tol"] = sum(1 for d in diffs if d <= SHADOW_TOL)
    out["shadow_max_diff"] = max(diffs) if diffs else None
    out["shadow_extra_fills"] = sum(1 for k, s in shadow.items() if s["status"] == "FILLED" and k not in jr)

    dec = _read_csv(os.path.join(obs_dir, "ledger_decisions.csv"))
    armed = [d for d in dec if d["decision"] == "ARMED"]
    bad = [d for d in armed if not (_t(d["range_end"]) <= _t(d["time"]) < _t(d["entry_end"]))]
    out["decisions"], out["armed"], out["lookahead_violations"] = len(dec), len(armed), len(bad)
    feats = [c for c in (dec[0].keys() if dec else []) if c.startswith(("gap_", "pre_", "range_pos", "vol_pct",
                                                                         "ev_tier1", "ctx1_prevday", "ctx2_prevday"))]
    out["feature_fill"] = {c: round(sum(1 for d in armed if d[c] != "") / max(1, len(armed)), 2) for c in feats}
    out["pass"] = out["zero_diff"] and out["ledger_match"] and out["lookahead_violations"] == 0 and \
        out["shadow_within_tol"] >= 0.95 * max(1, len(jr) - missing) and missing <= 0.02 * max(1, len(jr))
    return out


def build(spec, root, tag, out_path):
    rows = []
    for key, a in spec["assets"].items():
        obs = tagged_dir(root, a["run_id"], tag)
        actual = {e["event_id"]: e for e in load_run(obs)[1]} if os.path.isdir(obs) else {}
        shadow = {r["event_id"]: r for r in _read_csv(os.path.join(obs, "ledger_shadow.csv"))}
        for d in _read_csv(os.path.join(obs, "ledger_decisions.csv")):
            if d["decision"] != "ARMED":
                continue
            e, s = actual.get(d["event_id"]), shadow.get(d["event_id"], {})
            rows.append(dict(asset=key, role=a.get("role", "asset"), **d,
                             actual_filled=int(e is not None), actual_R=e["pnl_R"] if e else "",
                             actual_exit=e["exit_type"] if e else "", shadow_status=s.get("status", ""),
                             shadow_side=s.get("side", ""), shadow_R=s.get("shadow_R", ""),
                             shadow_exit=s.get("exit_type", "")))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["collect", "check", "build"])
    ap.add_argument("--assets", default=os.path.join(HERE, "aos_assets.json"))
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    spec, root = _spec(a.assets)
    if a.cmd == "collect":
        print(collect(root, a.tag), "ledger files copied")
    elif a.cmd == "check":
        results = []
        for key, asset in spec["assets"].items():
            obs = tagged_dir(root, asset["run_id"], a.tag)
            if not os.path.isdir(obs):
                print(f"[{key}] no run folder {os.path.basename(obs)}")
                continue
            r = check_asset(key, os.path.join(root, asset["run_id"]), obs)
            results.append(r)
            print(f"[{key}] pass={r['pass']} zero_diff={r['zero_diff']} events {r['n_base']}->{r['n_obs']} "
                  f"final {r['final_base']}->{r['final_obs']} volume_diffs={r['volume_diffs']} "
                  f"ledger={r['ledger_events']} match={r['ledger_match']} shadow ok {r['shadow_within_tol']}/"
                  f"{r['n_obs'] - r['shadow_missing']} missing={r['shadow_missing']} max_diff={r['shadow_max_diff']} "
                  f"extra_fills={r['shadow_extra_fills']} decisions={r['decisions']} armed={r['armed']} "
                  f"lookahead={r['lookahead_violations']}\n    fill {r['feature_fill']}")
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=1)
    else:
        out = a.out or os.path.join(root, "..", "tape", f"tape_{a.tag}.csv")
        print(build(spec, root, a.tag, out), "tape rows ->", os.path.relpath(out, HERE))


if __name__ == "__main__":
    main()
