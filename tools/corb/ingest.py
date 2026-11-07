"""INF-P2-T01 / T07 / T08: incremental ingest.

discover -> land (write-once) -> adapt + validate the runs that are new or changed -> load them (delete + copy per
run_key, one transaction) -> ops.ingest_state. A second ingest with nothing new writes 0 rows.

Runs come from tester/aos/runs (journal adapter + collected tester ledgers) and from live ledgers (VPS inbox and
Common\\Files *_live_*), which are split per month into kind=live runs under var/live/.
"""
import calendar
import csv
import glob
import hashlib
import json
import os
import re

from corb import contract, db, landing
from corb.inventory import sha256
from corb.paths import COMMON, INFRA, REPO, RUNS, TERMINAL, VAR, resolve
from corb.textio import read_text

STAGE = os.path.join(VAR, "stage")
LIVE = os.path.join(VAR, "live")
LIVE_CONFIG = os.path.join(INFRA, "live.json")
RE_LIVE = re.compile(r"^CORB_(\d+)_(.+)_live_(decisions|events|shadow)\.csv$")


def content_sha(run_dir):
    """What a run's DB rows depend on: its files, the contract and the adapter version."""
    h = hashlib.sha256(f"{contract.ADAPTER_VERSION}:{sha256(contract.PACKAGE)}".encode())
    for name in sorted(os.listdir(run_dir)):
        h.update(f"{name}:{sha256(os.path.join(run_dir, name))}".encode())
    return h.hexdigest()


def parse_set(path):
    inputs = {}
    for line in read_text(path).splitlines():
        line = line.strip()
        if line and not line.startswith(";") and "=" in line:
            k, v = line.split("=", 1)
            inputs[k.strip()] = v.split("||", 1)[0].strip()
    return inputs


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def build_live(files, config=None):
    """Live ledgers -> one run folder per deployment and month (event_id = magic-YYYYMMDD gives the month)."""
    if config is None:
        with open(LIVE_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
    groups = {}
    for p in files:
        m = RE_LIVE.match(os.path.basename(p))
        if m:
            groups.setdefault((m.group(1), m.group(2)), {})[m.group(3)] = p
    out = []
    for (base, symbol), kinds in sorted(groups.items()):
        dep = config["deployments"].get(base)
        if dep is None or "events" not in kinds or "decisions" not in kinds:
            continue
        inputs = parse_set(resolve(dep["preset"]) or dep["preset"])
        tables = {k: _read(p) for k, p in kinds.items()}
        months = sorted({r["event_id"].split("-")[1][:6] for r in tables["decisions"][1]})
        for ym in months:
            y, mo = int(ym[:4]), int(ym[4:])
            window = [f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"]
            run_id = f"v{dep['ea_version']}_{symbol}_{base}_{window[0]}_{window[1]}_{dep['deposit']}_live"
            d = os.path.join(LIVE, run_id)
            os.makedirs(d, exist_ok=True)
            rows = {}
            for kind, (header, data) in tables.items():
                rows[kind] = [r for r in data if r["event_id"].split("-")[1][:6] == ym]
                with open(os.path.join(d, f"ledger_{kind}.csv"), "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=header)
                    w.writeheader()
                    w.writerows(rows[kind])
            dec = rows["decisions"]
            meta = dict(run_id=run_id, symbol=symbol, version=dep["ea_version"], magic_base=int(base), window=window,
                        deposit=float(dep["deposit"]), final=None, point=dep["point"], inputs=inputs,
                        setups=[s for s, k in (("LON", "InpLonEnable"), ("NY", "InpNYEnable"), ("TKY", "InpTkyEnable"))
                                if inputs.get(k) == "true"],
                        n_events=len(rows.get("events", [])), armed_days=sum(r["decision"] == "ARMED" for r in dec),
                        sides_armed=sum(int(r["arm_buy"] or 0) + int(r["arm_sell"] or 0) for r in dec),
                        sides_lot_min=sum((r["skip_buy"] == "lot_min") + (r["skip_sell"] == "lot_min") for r in dec),
                        counters={}, closefail_dates={}, source=dict(live_files=sorted(kinds.values())))
            with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=1)
            out.append(d)
    return out


def discover():
    with open(LIVE_CONFIG, encoding="utf-8") as f:
        inbox = resolve(json.load(f)["inbox"])
    common = sorted(glob.glob(os.path.join(COMMON, "CycleORB", "CORB_*.csv")))
    vps = sorted(glob.glob(os.path.join(inbox, "CORB_*_live_*.csv"))) if inbox else []
    return dict(
        run_dirs=sorted(d for d in glob.glob(os.path.join(RUNS, "*")) if os.path.exists(os.path.join(d, "meta.json"))),
        journals_terminal=sorted(glob.glob(os.path.join(TERMINAL, "Tester", "logs", "*.log"))),
        journals_repo=sorted(glob.glob(os.path.join(REPO, "tester", "*.log"))),
        ledgers_common=common, ledgers_vps=vps,
        live=[p for p in common if "_live_" in p] + vps)


def ingest():
    src = discover()
    landed = {}
    run_files = [os.path.join(d, f) for d in src["run_dirs"] for f in sorted(os.listdir(d))]
    for origin, files in (("repo", run_files + src["journals_repo"]), ("terminal", src["journals_terminal"]),
                          ("common", src["ledgers_common"]), ("vps", src["ledgers_vps"])):
        landed[origin] = landing.land(files, origin)
    live_dirs = build_live(src["live"])

    state = dict(ln.split("\t") for ln in db.psql("SELECT run_key, content_sha256 FROM ops.ingest_state;").splitlines()
                 if ln)
    baselines = contract.baseline_run_ids()
    res = contract.resources()
    tables = {name: [] for name in res}
    changed, unchanged, rejected, seen = [], 0, [], {}
    for d in src["run_dirs"] + live_dirs:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            key = contract.run_key(json.load(f))
        if key in seen:
            rejected.append(dict(run=os.path.basename(d), problem=f"run_key collides with {seen[key]}"))
            continue
        seen[key] = os.path.basename(d)
        csha = content_sha(d)
        if state.get(key) == csha:
            unchanged += 1
            continue
        rows = contract.adapt(d, baselines, kind="live" if d.startswith(LIVE) else None)
        bad = {k: contract.validate(k, v) for k, v in rows.items()}
        if any(bad.values()):
            rejected.append(dict(run=os.path.basename(d), problem=f"{sum(map(len, bad.values()))} contract violations"))
            continue
        for k, v in rows.items():
            tables[k] += v
        changed.append((key, csha))

    os.makedirs(STAGE, exist_ok=True)
    for name, r in res.items():
        cols = [f["name"] for f in r["schema"]["fields"]]
        with open(os.path.join(STAGE, name + ".csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in tables[name]:
                w.writerow(["" if row.get(c) is None else ("true" if row[c] is True else "false" if row[c] is False
                                                           else row[c]) for c in cols])
    with open(os.path.join(STAGE, "ingest_state.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_key", "content_sha256"])
        w.writerows(changed)
    landing.export_source_files()
    inserted = db.load_incremental([k for k, _ in changed])
    return dict(runs_seen=len(seen), runs_loaded=len(changed), runs_unchanged=unchanged, rejected=rejected,
                live_runs=len(live_dirs), landed=landed, rows_staged={k: len(v) for k, v in tables.items()},
                source_files_inserted=inserted)


def import_ouroboros(spec_path=None):
    """INF-P2-T08: land every frozen Ouroboros slice (sha256 must still match infra/sources.json)."""
    from corb import sources
    with open(spec_path or sources.SOURCES, encoding="utf-8") as f:
        spec = json.load(f)
    o = spec["ouroboros"]
    root = os.environ.get("CORB_OUROBOROS_DIR") or o.get("root")
    results = []
    for sl in o["slices"]:
        if not sl.get("path") or not sl.get("sha256"):
            continue
        p = os.path.join(root, sl["path"])
        if not os.path.isfile(p) or sha256(p) != sl["sha256"]:
            results.append(dict(id=sl["id"], status="refused: changed or missing since freeze"))
            continue
        r = landing.land([p], "ouroboros", extra=dict(source_commit=o["source_commit"], slice=sl["id"]))
        results.append(dict(id=sl["id"], status="landed" if r["landed"] else "duplicate"))
    return results
