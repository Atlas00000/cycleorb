"""INF-P5-T04 / T07: infra tests.

preset_lint()   every .set under Presets/: exactly the EA's inputs (none missing: MT5 keeps the previous value;
                none unknown), string inputs < 250 characters (MT5 truncates at 255 silently), skip dates parse and,
                for the live / export presets, reach >= 90 days ahead
golden()        stable health-vector hash for frozen baseline runs (infra/golden/health_vectors.json)
build_image()   the pinned job image (infra/docker/jobs)
replay()        the same corb commands on the host and inside the job image: identical results
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date

from corb import db
from corb.paths import INFRA, REPO, RUNS, TOOLS, VAR
from corb.textio import read_text

GOLDEN = os.path.join(INFRA, "golden", "health_vectors.json")
IMAGE = "cycleorb-jobs"
GOLDEN_RUNS = {"DE40": "v1.11_DE30_26110310_2025-07-01_2026-10-31_1000",
               "EURUSD-NY": "v1.11_EURUSD_26110200_2025-07-01_2026-10-31_1000",
               "US500": "v1.11_SPX500_26110900_2025-07-01_2026-10-31_1000"}
GOLDEN_FIELDS = ("n", "WR", "AW", "AL", "R", "BWR", "BM", "E", "E_N", "PF", "Leak", "EF", "M", "maxdd_R", "BM_worst")


def ea_inputs():
    names, strings = set(), set()
    for f in glob.glob(os.path.join(REPO, "Include", "*.mqh")) + [os.path.join(REPO, "CycleORB.mq5")]:
        for m in re.finditer(r"(?m)^\s*(?:sinput|input)\s+([\w ]+?)\s+(Inp\w+)\s*=", read_text(f)):
            names.add(m.group(2))
            if m.group(1).strip() == "string":
                strings.add(m.group(2))
    return names, strings


def _dates(raw):
    out = []
    for tok in [t.strip() for t in raw.split(",") if t.strip()]:
        s = tok if len(tok) == 8 else "20" + tok
        out.append(date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    return out


def preset_lint(today=None):
    from corb.ingest import parse_set
    today = today or date.today()
    names, strings = ea_inputs()
    problems, warnings, checked = [], [], 0
    for path in sorted(glob.glob(os.path.join(REPO, "Presets", "**", "*.set"), recursive=True)):
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        inputs = parse_set(path)
        checked += 1
        for k in sorted(names - set(inputs)):
            problems.append(f"{rel}: missing input {k} (MT5 would keep the previous value)")
        for k in sorted(set(inputs) - names):
            problems.append(f"{rel}: unknown input {k}")
        for k in strings & set(inputs):
            if len(inputs[k]) >= 250:
                problems.append(f"{rel}: {k} is {len(inputs[k])} characters (MT5 truncates at 255)")
        try:
            dates = _dates(inputs.get("InpSkipDates", ""))
        except ValueError as e:
            problems.append(f"{rel}: InpSkipDates does not parse ({e})")
            continue
        live = "/AOS/AOS-P3-REC_" in "/" + rel or "/EXP/" in "/" + rel
        if live and dates and (max(dates) - today).days < 90:
            problems.append(f"{rel}: skip dates end {max(dates)} (< 90 days ahead)")
        elif dates and (max(dates) - today).days < 180:
            warnings.append(f"{rel}: skip dates end {max(dates)}")
    return dict(presets=checked, ea_inputs=len(names), string_inputs=len(strings), problems=problems,
                warnings=warnings)


def _vectors():
    from corb_bench import load_run, score
    out = {}
    for asset, run_id in GOLDEN_RUNS.items():
        meta, events = load_run(os.path.join(RUNS, run_id))
        s = score(meta, events, 0.01, mc_iters=200)
        out[asset] = {k: (round(s[k], 9) if isinstance(s[k], float) else s[k]) for k in GOLDEN_FIELDS}
    return out


def golden(update=False):
    vec = _vectors()
    digest = hashlib.sha256(json.dumps(vec, sort_keys=True).encode()).hexdigest()
    if update or not os.path.exists(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as f:
            json.dump(dict(sha256=digest, runs=GOLDEN_RUNS, vectors=vec), f, indent=1)
    with open(GOLDEN, encoding="utf-8") as f:
        want = json.load(f)
    return dict(ok=want["sha256"] == digest, expected=want["sha256"], got=digest)


def build_image():
    ctx = os.path.join(INFRA, "docker", "jobs")
    p = subprocess.run(["docker", "build", "-t", f"{IMAGE}:latest", ctx], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError(p.stderr[-3000:])
    return subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", f"{IMAGE}:latest"], capture_output=True,
                          text=True).stdout.strip()


def in_container(args, timeout=1800):
    cmd = ["docker", "run", "--rm", "--network", db.NETWORK, "-e", "CORB_DB_HOST=db",
           "-v", f"{REPO}:/repo", "-v", f"{VAR}:/corb/var", f"{IMAGE}:latest", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout[-4000:], p.stderr[-2000:]


def _card_path(recipe):
    return os.path.join(VAR, "scorecards", recipe + ".json")


def _card(recipe):
    """The scorecard the last run wrote, or {} if it wrote none (a crash must not reuse an older card)."""
    if not os.path.exists(_card_path(recipe)):
        return {}
    with open(_card_path(recipe), encoding="utf-8") as f:
        return json.load(f)


def _same(a, b, tol=1e-9):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    return a == b


REPLAYS = [(["baseline", "check"], "INF-P0-T03_train_baselineCheck", "failures"),
           (["train", "regression"], "INF-P4-T01_train_harnessRegression_AOS-P2-P4", "checks"),
           (["db", "check"], "INF-P1-T04_store_rebuildEvents_allRuns", "failures")]


def replay():
    """Host vs container: the same command must give the same verdict and the same numbers."""
    out = []
    for args, recipe, field in REPLAYS:
        if os.path.exists(_card_path(recipe)):
            os.remove(_card_path(recipe))
        h = subprocess.run([sys.executable, "-m", "corb", *args], cwd=TOOLS, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        host = _card(recipe)
        if os.path.exists(_card_path(recipe)):
            os.remove(_card_path(recipe))
        code, so, se = in_container(args)
        box = _card(recipe)
        ran = bool(host) and bool(box)
        out.append(dict(command=" ".join(args), host_exit=h.returncode, container_exit=code,
                        host_verdict=host.get("verdict", "NO_CARD"), container_verdict=box.get("verdict", "NO_CARD"),
                        same=ran and host["verdict"] == box["verdict"] and _same(host.get(field), box.get(field)),
                        stderr=(h.stderr[-300:] if not host else "") + (se[-300:] if not box else "")))
    return out
