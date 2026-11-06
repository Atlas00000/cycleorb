"""INF-P1-T05: landing zone. Files are copied once to <root>/<origin>/<yyyy-mm-dd>/<sha256>/<name>, made read-only,
and recorded in <root>/manifest.jsonl. Same content again = duplicate (not copied). verify() re-hashes every landed
file: a changed or missing file is reported and must never be loaded.
"""
import csv
import json
import os
import shutil
import stat
from datetime import datetime

from corb.inventory import classify, sha256
from corb.paths import VAR, portable

ROOT = os.path.join(VAR, "landing")


def _manifest(root):
    path = os.path.join(root, "manifest.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def land(paths, origin, root=ROOT):
    os.makedirs(root, exist_ok=True)
    known = {m["sha256"] for m in _manifest(root)}
    today = datetime.now().strftime("%Y-%m-%d")
    landed, duplicates = [], 0
    with open(os.path.join(root, "manifest.jsonl"), "a", encoding="utf-8") as man:
        for src in paths:
            digest = sha256(src)
            if digest in known:
                duplicates += 1
                continue
            dest_dir = os.path.join(root, origin, today, digest)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(src))
            shutil.copyfile(src, dest)
            os.chmod(dest, stat.S_IREAD)
            rec = dict(sha256=digest, origin=origin, kind=classify(portable(src)) or "other", src_path=portable(src),
                       landed_path=os.path.relpath(dest, root).replace("\\", "/"), bytes=os.path.getsize(dest),
                       landed_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            man.write(json.dumps(rec) + "\n")
            known.add(digest)
            landed.append(rec)
    return dict(landed=len(landed), duplicates=duplicates)


def verify(root=ROOT):
    bad = []
    for m in _manifest(root):
        p = os.path.join(root, m["landed_path"])
        if not os.path.exists(p):
            bad.append(dict(sha256=m["sha256"], path=m["landed_path"], problem="missing"))
        elif sha256(p) != m["sha256"]:
            bad.append(dict(sha256=m["sha256"], path=m["landed_path"], problem="modified"))
    return bad


def export_source_files(root=ROOT):
    """raw.source_file rows (one per landed sha256) as CSV for the loader."""
    out = os.path.join(root, "source_file.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_sha256", "origin", "kind", "src_path", "landed_path", "bytes", "landed_at"])
        for m in _manifest(root):
            w.writerow([m["sha256"], m["origin"], m["kind"], m["src_path"], m["landed_path"], m["bytes"], m["landed_at"]])
    return out
