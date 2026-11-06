"""INF-P0-T04: check the evidence-source register (infra/sources.json) and measure broker history depth."""
import glob
import json
import os

from corb.paths import INFRA, OUROBOROS, resolve

SOURCES = os.path.join(INFRA, "sources.json")
RECIPE = "INF-P0-T04_data_sourcesRegister"


def _files(path, pattern=None):
    if path is None or not os.path.exists(path):
        return []
    if os.path.isfile(path):
        return [path]
    return [p for p in glob.glob(os.path.join(path, "**", pattern or "*"), recursive=True) if os.path.isfile(p)]


def broker_depth(bases, symbols):
    """First / last month of real ticks (*.tkc = YYYYMM) and the years of M1 bars (*.hcc = YYYY) per symbol."""
    out = {}
    for s in symbols:
        ticks = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(bases, "ticks", s, "*.tkc")))
        years = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(bases, "history", s, "*.hcc")))
        out[s] = dict(ticks_from=ticks[0] if ticks else None, ticks_to=ticks[-1] if ticks else None,
                      tick_months=len(ticks), m1_years=[int(y) for y in years if y.isdigit()])
    return out


def check(spec=None):
    if spec is None:
        with open(SOURCES, encoding="utf-8") as f:
            spec = json.load(f)
    rows = []
    for s in spec["sources"]:
        if s.get("status") == "planned":
            rows.append(dict(id=s["id"], status="planned", files=0, bytes=0))
            continue
        path = resolve(s["location"]) if s.get("location") else None
        files = _files(path, s.get("pattern"))
        status = "not_located" if path is None else ("ok" if files else "missing")
        if status == "ok" and not s.get("valid_from"):
            status = "no_valid_from"
        rows.append(dict(id=s["id"], status=status, files=len(files), bytes=sum(os.path.getsize(p) for p in files)))

    o = spec["ouroboros"]
    slices = []
    for sl in o["slices"]:
        if sl["path"] is None:
            st = "path_unknown"
        elif not OUROBOROS:
            st = "root_not_set"
        else:
            st = "ok" if _files(resolve("%OUROBOROS%/" + sl["path"])) else "missing"
        slices.append(dict(id=sl["id"], priority=sl["priority"], status=st))

    bases = resolve(spec["broker"]["bases"])
    depth = broker_depth(bases, spec["broker"]["symbols"]) if bases and os.path.isdir(bases) else {}
    local_ok = all(r["status"] in ("ok", "planned") for r in rows)
    ouroboros_ok = OUROBOROS is not None and o.get("source_commit") and all(s["status"] == "ok" for s in slices)
    verdict = "ACCEPT" if local_ok and ouroboros_ok else ("HOLD" if local_ok else "REJECT")
    open_items = [f"{r['id']}: {r['status']}" for r in rows if r["status"] not in ("ok", "planned")]
    if not ouroboros_ok:
        open_items.append(f"Ouroboros: {sum(s['status'] != 'ok' for s in slices)} of {len(slices)} slices not located "
                          f"(set CORB_OUROBOROS_DIR, fill null paths and source_commit)")
    return dict(verdict=verdict, sources=rows, ouroboros=dict(root_set=OUROBOROS is not None,
                                                               source_commit=o.get("source_commit"), slices=slices),
                broker_depth=depth, open=open_items)
