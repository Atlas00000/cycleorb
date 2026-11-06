"""INF-P0-T02: inventory of every evidence file (run folders, ledgers, tape, journals, presets, specs) with sha256.

Finds exact file duplicates and runs whose events.csv is identical (the same evidence under two names).
"""
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime

from corb.paths import COMMON, REPO, RUNS, TERMINAL, git_info, portable

REPO_SCOPES = ("tester", "Presets", "tools")
SKIP_DIRS = {"__pycache__", ".git", "var"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(path):
    p = path.replace("\\", "/")
    name = os.path.basename(p)
    if "/runs/" in p:
        return "run_" + os.path.splitext(name)[0]
    if "/tape/" in p:
        return "tape"
    if p.endswith(".log"):
        return "journal"
    if p.endswith(".ini"):
        return "tester_ini"
    if p.endswith(".set"):
        return "preset"
    if "/Common/" in p or p.startswith("%COMMON%"):
        if name == "events.csv":
            return "calendar"
        for k in ("decisions", "events", "shadow"):
            if name.endswith(f"_{k}.csv"):
                return "ledger_" + k
    if p.endswith(".json"):
        return "spec" if "/tools/" in p or p.startswith("%REPO%/tools") else "scorecard"
    return None


def parse_run_id(run_id):
    """v<ver>_<symbol>_<magic>_<from>_<to>_<deposit>[_<tag>]"""
    parts = run_id.split("_")
    version = parts[0][3:] if parts[0].startswith("vle") else parts[0][1:]
    return dict(version=version, symbol=parts[1], magic_base=int(parts[2]),
                window=[parts[3], parts[4]], deposit=float(parts[5]), tag="_".join(parts[6:]) or None)


def _walk(root, scopes=None):
    tops = [os.path.join(root, s) for s in scopes] if scopes else [root]
    for top in tops:
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for name in sorted(files):
                yield os.path.join(d, name)


def build(external=True):
    roots = [(REPO, REPO_SCOPES)]
    if external:
        roots += [(os.path.join(COMMON, "CycleORB"), None), (os.path.join(TERMINAL, "Tester", "logs"), None)]
    files = []
    for root, scopes in roots:
        if not os.path.isdir(root):
            continue
        for path in _walk(root, scopes):
            kind = classify(portable(path))
            if kind:
                files.append(dict(path=portable(path), kind=kind, bytes=os.path.getsize(path), sha256=sha256(path)))
    by_path = {f["path"]: f for f in files}

    runs = []
    for run_id in sorted(os.listdir(RUNS)) if os.path.isdir(RUNS) else []:
        folder = os.path.join(RUNS, run_id)
        meta_path = os.path.join(folder, "meta.json")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        members = sorted((f for p, f in by_path.items() if p.startswith(portable(folder) + "/")),
                         key=lambda f: f["path"])
        events = next((f["sha256"] for f in members if f["path"].endswith("/events.csv")), None)
        folder_hash = hashlib.sha256("\n".join(f"{os.path.basename(f['path'])}:{f['sha256']}"
                                               for f in members).encode()).hexdigest()
        runs.append(dict(run_id=run_id, **parse_run_id(run_id), n_events=meta.get("n_events"),
                         armed_days=meta.get("armed_days"), final=meta.get("final"),
                         events_sha256=events, folder_sha256=folder_hash))

    same_file = defaultdict(list)
    for f in files:
        same_file[f["sha256"]].append(f["path"])
    same_events = defaultdict(list)
    for r in runs:
        if r["events_sha256"]:
            same_events[r["events_sha256"]].append(r["run_id"])
    counts = defaultdict(int)
    for f in files:
        counts[f["kind"]] += 1
    return dict(
        task="INF-P0-T02", generated_at=datetime.now().isoformat(timespec="seconds"), git=git_info(),
        summary=dict(files=len(files), bytes=sum(f["bytes"] for f in files), runs=len(runs),
                     kinds=dict(sorted(counts.items())),
                     duplicate_file_groups=sum(1 for v in same_file.values() if len(v) > 1),
                     same_events_groups=sum(1 for v in same_events.values() if len(v) > 1)),
        runs=runs,
        duplicates=dict(
            files=[dict(sha256=k, paths=v) for k, v in sorted(same_file.items()) if len(v) > 1],
            same_events=[dict(events_sha256=k, run_ids=v) for k, v in sorted(same_events.items()) if len(v) > 1]),
        files=sorted(files, key=lambda f: f["path"]))
