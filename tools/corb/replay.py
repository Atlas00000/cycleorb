"""INF-P2-T05: end-to-end replay of a raw tester journal.

journal -> corb_parse.py into var/replay/<name>/ (never into tester/aos/runs) -> for every baseline run found there:
  1. events.csv is byte-identical to the committed run folder (the parser is deterministic)
  2. the health vector equals tools/aos_baseline.json within the CO-FX tolerances
  3. the replayed folder adapts to the contract with 0 violations
"""
import os
import subprocess
import sys

from corb import contract
from corb.baseline import FROZEN_FIELDS, check
from corb.inventory import sha256
from corb.paths import RUNS, TOOLS, VAR


def replay(journal, version):
    import json
    from corb_bench import load_run, score
    name = os.path.splitext(os.path.basename(journal))[0]
    out = os.path.join(VAR, "replay", f"{name}_v{version}")
    os.makedirs(out, exist_ok=True)
    p = subprocess.run([sys.executable, os.path.join(TOOLS, "corb_parse.py"), journal, "--out", out,
                        "--version", version], capture_output=True, text=True, cwd=TOOLS)
    if p.returncode:
        raise RuntimeError(p.stderr)
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    with open(os.path.join(TOOLS, "aos_baseline.json"), encoding="utf-8") as f:
        frozen = json.load(f)["assets"]
    checks, found = [], []
    for key, a in assets.items():
        replayed = os.path.join(out, a["run_id"])
        if not os.path.isdir(replayed):
            continue
        found.append(key)
        committed = os.path.join(RUNS, a["run_id"])
        checks.append(check(f"{key}.events_byte_identical", sha256(os.path.join(committed, "events.csv")),
                            sha256(os.path.join(replayed, "events.csv")), 0))
        checks.append(check(f"{key}.decisions_byte_identical", sha256(os.path.join(committed, "decisions.csv")),
                            sha256(os.path.join(replayed, "decisions.csv")), 0))
        meta, events = load_run(replayed)
        s = score(meta, events, a["f_op"])
        checks += [check(f"{key}.{k}", frozen[key][k], s[k], tol) for k, tol in FROZEN_FIELDS]
        rows = contract.adapt(replayed)
        checks.append(check(f"{key}.contract_violations", 0, sum(len(contract.validate(n, r)) for n, r in rows.items()), 0))
    return dict(journal=journal, out=out, runs_parsed=len(os.listdir(out)), baselines_found=found), checks
