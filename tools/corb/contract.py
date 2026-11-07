"""INF-P1-T01 / T03: the adapter contract (infra/contract/datapackage.json).

adapt(run_dir)        run folder -> {resource: [rows]} with deterministic keys (run_key, event_id, leg_id)
validate(name, rows)  rows -> violations against the resource schema (types, required, enum, pattern, bounds,
                      primary key, x-checks)
ddl()                 CREATE TABLE statements generated from the same contract (used for the migrations)
"""
import csv
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta

from corb.inventory import parse_run_id, sha256
from corb.paths import INFRA, TOOLS

PACKAGE = os.path.join(INFRA, "contract", "datapackage.json")
SETUP_OFFSET = {"LON": 1, "NY": 2, "TKY": 3}
SETUP_BY_OFFSET = {v: k for k, v in SETUP_OFFSET.items()}
FEATURES = ["atr_pct", "cost_pct", "spread_avg_pt", "spread_live_pt", "vol_pct", "trend_side", "range_atr", "gap_atr",
            "pre_drift_atr", "range_pos_prev", "brk_prev_high", "brk_prev_low", "inside_prev", "outside_prev", "nr4",
            "nr7", "sma_dist_hi_atr", "sma_dist_lo_atr", "dow", "ev_tier1_entry", "ev_tier1_hold", "ev_next_min",
            "ev_first_hold", "opex", "quad_witching", "ctx1_sym", "ctx1_prevday_atr", "ctx1_lookback_atr", "ctx2_sym",
            "ctx2_prevday_atr", "ctx2_lookback_atr", "ctx3_sym", "ctx3_prevday_atr", "ctx3_lookback_atr"]
SQL_TYPE = {"string": "text", "integer": "bigint", "number": "double precision", "boolean": "boolean",
            "datetime": "timestamptz", "date": "date"}
ADAPTER_VERSION = "2"   # bump when a derivation changes: incremental ingest re-loads every run


def _cost_flags(swap, money):
    return (f"spread=measured_in_fills;commission=declared_zero;swap={swap};slippage=entry_measured_in_fills;"
            f"money={money}")


def package():
    with open(PACKAGE, encoding="utf-8") as f:
        return json.load(f)


def resources():
    return {r["name"]: r for r in package()["resources"]}


def canonical_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run_key(meta):
    """Same build inputs on the same data -> same key. Determinism (System Profile N9) then implies identical events."""
    ident = dict(ea_version=meta["version"], symbol=meta["symbol"], preset_sha256=canonical_sha(meta["inputs"]),
                 window=meta["window"], deposit=meta["deposit"], model="real_ticks")
    return canonical_sha(ident)[:16]


# ---------------------------------------------------------------- adapter
def _num(s):
    return None if s in (None, "") else float(s)


def _int(s):
    return None if s in (None, "") else int(float(s))


def _utc(s, offset_h, fmt="%Y-%m-%d %H:%M:%S"):
    if not s:
        return None
    return (datetime.strptime(s, fmt) - timedelta(hours=offset_h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_utc(s, offset_h):
    return _utc(s, offset_h, "%Y.%m.%d %H:%M:%S")


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _kind(run_id, tag, baselines):
    if run_id in baselines:
        return "baseline"
    return "variant" if tag else "reference"


def baseline_run_ids():
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        return {a["run_id"] for a in json.load(f)["assets"].values()}


def _ledger_time(s):
    return s.replace(".", "-", 2) if s else ""


def ledger_as_journal(led_dec, led_evt, point):
    """Ledger rows in the journal parser's row format, with corb_parse.finish's derivations (risk_px, c_spread_R,
    c_slip_R, slip_entry_R, hold_min). One adapter path then serves both sources, and they reconcile field by field."""
    by_id, decisions = {}, []
    for d in led_dec or []:
        if d["event_id"] in by_id:
            continue
        by_id[d["event_id"]] = d
        armed = d["decision"] == "ARMED"
        hi, lo = _num(d["hi"]), _num(d["lo"])
        decisions.append(dict(
            date=d["local_day"].replace(".", "-"), setup=d["setup"], decision=d["decision"], reason=d["reason"],
            atr_pct=d["atr_pct"], spread_pt=d["spread_avg_pt"] if armed else "", cost_pct=d["cost_pct"] if armed else "",
            range_pt=str(round((hi - lo) / point)) if armed and hi is not None and lo is not None else "",
            risk_money=d["risk_money"] if armed else "", trend=d["trend_side"] if armed else "",
            sides_placed=str(int(d["placed_buy"] or 0) + int(d["placed_sell"] or 0)),
            sides_lot_min=str((d["skip_buy"] == "lot_min") + (d["skip_sell"] == "lot_min"))))
    events = []
    for e in led_evt or []:
        d = by_id.get(e["event_id"], {})
        sign = 1 if e["side"] == "buy" else -1
        req, fill, stop = float(e["entry_requested"]), float(e["entry_price"]), float(e["initial_stop"])
        risk_px = abs(req - stop)
        spread_px = (_num(d.get("spread_avg_pt")) or 0.0) * point
        t_in, t_out = _ledger_time(e["entry_time"]), _ledger_time(e["exit_time"])
        hold = (datetime.fromisoformat(t_out) - datetime.fromisoformat(t_in)).total_seconds() / 60
        risk, eq = _num(e["risk_ccy"]), _num(e["equity_at_open"])
        events.append(dict(
            event_id=e["event_id"], magic=e["magic"], setup=e["setup"], side=e["side"],
            day=(d.get("local_day") or e["entry_time"][:10]).replace(".", "-"), place_time="", entry_time=t_in,
            entry_requested=e["entry_requested"], entry_price=e["entry_price"], exit_time=t_out,
            exit_price=e["exit_price"], exit_type=e["exit_type"], close_reason="", initial_stop=e["initial_stop"],
            take_profit=e["take_profit"], volume=e["volume"], risk_px=str(risk_px), pnl_R=e["pnl_R"],
            pnl_ccy_est=e["pnl_ccy"], risk_ccy_est=e["risk_ccy"], equity_at_open_est=e["equity_at_open"],
            risk_pct_est="" if not (risk and eq) else str(100 * risk / eq), atr_pct=d.get("atr_pct", ""),
            trend=d.get("trend_side", ""), spread_pt=d.get("spread_avg_pt", ""),
            c_spread_R=str(spread_px / risk_px), c_slip_R=str(0.5 * spread_px * (1 + (e["exit_type"] != "TP")) / risk_px),
            slip_entry_R=str(sign * (fill - req) / risk_px), hold_min=str(round(hold, 1))))
    return events, decisions


def adapt(run_dir, baselines=frozenset(), kind=None):
    """kind overrides the derived run kind (the live path passes 'live')."""
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    inputs = meta["inputs"]
    if inputs.get("InpServerTZ") != "1":
        raise ValueError(f"{meta['run_id']}: only fixed-offset server clocks are supported (InpServerTZ=1)")
    off = int(inputs.get("InpServerFixedOffsetH", "0"))
    key = run_key(meta)
    rid = parse_run_id(meta["run_id"])
    led_dec = _read(os.path.join(run_dir, "ledger_decisions.csv"))
    led_evt = _read(os.path.join(run_dir, "ledger_events.csv"))
    led_shadow = _read(os.path.join(run_dir, "ledger_shadow.csv"))
    events = _read(os.path.join(run_dir, "events.csv"))
    decisions = _read(os.path.join(run_dir, "decisions.csv"))
    events_file = os.path.join(run_dir, "events.csv")
    if events is None:
        if led_evt is None:
            raise ValueError(f"{meta['run_id']}: neither events.csv nor ledger_events.csv")
        events, decisions = ledger_as_journal(led_dec, led_evt, float(meta["point"]))
        events_file = os.path.join(run_dir, "ledger_events.csv")
    decisions = decisions or []
    money = {e["event_id"]: e for e in led_evt or []}
    closefail = set(meta.get("closefail_dates") or {})
    n = len(events)
    span = ((date.fromisoformat(events[-1]["day"]) - date.fromisoformat(events[0]["day"])).days + 1) if n else 0

    out = dict(run=[dict(
        run_key=key, run_id=meta["run_id"], ea_name="CycleORB", ea_version=meta["version"], symbol=meta["symbol"],
        magic_base=int(meta["magic_base"]), setups="|".join(meta.get("setups", [])),
        window_from=meta["window"][0], window_to=meta["window"][1], deposit=float(meta["deposit"]),
        final_balance=meta.get("final"), run_tag=rid["tag"] or "",
        kind=kind or _kind(meta["run_id"], rid["tag"], baselines),
        designed_rr=float(inputs["InpTargetR"]), risk_definition="hard_stop", regime_filtered=True,
        baseline_frequency=(n / (span / 30.44) * 90 / 30.44) if span else None,
        costs_defaulted="slippage_prior", server_utc_offset_h=off, preset_sha256=canonical_sha(inputs),
        events_sha256=sha256(events_file),
        journal_sha16=(meta.get("source") or {}).get("journal_sha256_16"), n_events=n,
        armed_days=meta.get("armed_days"), sides_armed=meta.get("sides_armed"), sides_lot_min=meta.get("sides_lot_min"),
        has_ledger=led_dec is not None)])

    out["decision"], seen = [], set()
    for d in decisions:
        magic = int(meta["magic_base"]) + SETUP_OFFSET[d["setup"]]
        eid = f"{magic}-{d['date'].replace('-', '')}"
        if eid in seen and d["reason"] == "already_traded":
            continue                       # restart guard re-evaluation of the same setup-day
        seen.add(eid)
        out["decision"].append(dict(
            run_key=key, event_id=eid, local_day=d["date"], setup=d["setup"], magic=magic, decision=d["decision"],
            reason=d["reason"], atr_pct=_num(d["atr_pct"]), spread_pt=_num(d["spread_pt"]), cost_pct=_num(d["cost_pct"]),
            range_pt=_num(d["range_pt"]), risk_money=_num(d["risk_money"]), trend=_int(d["trend"]),
            sides_placed=_int(d["sides_placed"]), sides_lot_min=_int(d["sides_lot_min"])))

    out["event"], out["leg"] = [], []
    defaulted_swap = False
    for e in events:
        entry, exit_ = _utc(e["entry_time"], off), _utc(e["exit_time"], off)
        overnight = entry[:10] != exit_[:10]
        leak = overnight or e["day"] in closefail or entry[:10] in closefail
        m = money.get(e["event_id"])
        if m and m["risk_ccy"] and m["pnl_ccy"]:
            # ledger money is the account's actual record: deal profit + swap + commission (Ledger.mqh)
            risk_ccy, equity, net = float(m["risk_ccy"]), _num(m["equity_at_open"]), float(m["pnl_ccy"])
            residual = net - float(e["pnl_R"]) * risk_ccy
            swap_cost, swap_flag, src = (-residual, "measured_ledger_residual", "ledger") if overnight \
                else (0.0, "zero_intraday", "ledger")
        else:
            risk_ccy, equity, net = _num(e["risk_ccy_est"]), _num(e["equity_at_open_est"]), _num(e["pnl_ccy_est"])
            swap_cost, swap_flag, src = 0.0, ("defaulted_zero" if overnight else "zero_intraday"), "journal_estimate"
        defaulted_swap |= swap_flag == "defaulted_zero"
        out["event"].append(dict(
            run_key=key, event_id=e["event_id"], signal_tag=e["setup"], magic=int(e["magic"]), local_day=e["day"],
            n_legs=1, risk_px=float(e["risk_px"]), risk_ccy=risk_ccy, equity_at_open=equity,
            risk_pct=100 * risk_ccy / equity if risk_ccy and equity else None, pnl_R=float(e["pnl_R"]),
            exit_type=e["exit_type"],
            close_reason=e["close_reason"], c_spread_R=_num(e["c_spread_R"]), c_slip_prior_R=_num(e["c_slip_R"]),
            slip_entry_R=_num(e["slip_entry_R"]), hold_min=_num(e["hold_min"]), atr_pct=_num(e["atr_pct"]),
            trend=_int(e["trend"]), calendar_leak=leak))
        spread = None if risk_ccy is None or e["c_spread_R"] == "" else float(e["c_spread_R"]) * risk_ccy
        slip = None if risk_ccy is None or e["slip_entry_R"] == "" else float(e["slip_entry_R"]) * risk_ccy
        direction = "long" if e["side"] == "buy" else "short"
        out["leg"].append(dict(
            run_key=key, leg_id=f"{key}:{e['event_id']}:{direction}", event_id=e["event_id"], symbol=meta["symbol"],
            direction=direction, place_time=_utc(e["place_time"], off), entry_time=entry,
            entry_price=float(e["entry_price"]), entry_requested=_num(e["entry_requested"]), exit_time=exit_,
            exit_price=float(e["exit_price"]), exit_requested=None, initial_stop=float(e["initial_stop"]),
            take_profit=_num(e["take_profit"]), volume=float(e["volume"]),
            pnl_gross_ccy=None if None in (net, spread, slip) else net + spread + slip + swap_cost,
            cost_spread_ccy=spread, cost_commission_ccy=0.0, cost_swap_ccy=swap_cost, cost_slippage_ccy=slip,
            pnl_net_ccy=net, cost_flags=_cost_flags(swap_flag, src)))
    if defaulted_swap:
        out["run"][0]["costs_defaulted"] = "slippage_prior,swap_overnight"

    out["shadow"], seen = [], set()
    for s in led_shadow or []:
        if s["event_id"] in seen:
            continue
        seen.add(s["event_id"])
        out["shadow"].append(dict(
            run_key=key, event_id=s["event_id"], setup=s["setup"], arm_buy=s["arm_buy"] == "1",
            arm_sell=s["arm_sell"] == "1", withheld_buy=s["withheld_buy"], withheld_sell=s["withheld_sell"],
            status=s["status"], side=s["side"], fill_time=_ledger_utc(s["fill_time"], off),
            fill_price=_num(s["fill_price"]), exit_time=_ledger_utc(s["exit_time"], off),
            exit_price=_num(s["exit_price"]), exit_type=s["exit_type"], shadow_R=_num(s["shadow_R"])))

    out["feature"], seen = [], set()
    for d in led_dec or []:
        if d["event_id"] in seen:
            continue
        seen.add(d["event_id"])
        as_of, at = _ledger_utc(d["range_end"], off), _ledger_utc(d["time"], off)
        for f in FEATURES:
            v = d.get(f, "")
            if v == "":
                continue
            try:
                num, text = float(v), None
            except ValueError:
                num, text = None, v
            out["feature"].append(dict(run_key=key, event_id=d["event_id"], feature=f, value_num=num, value_text=text,
                                       as_of_ts=as_of, decision_ts=at, source="ea"))

    counters = dict(meta.get("counters") or {})
    counters["sides_lot_min"] = meta.get("sides_lot_min") or 0
    counters["closefail_days"] = len(closefail)
    out["funnel"] = [dict(run_key=key, counter=k, value=int(v)) for k, v in sorted(counters.items())]
    return out


def build_all(runs_root, out_dir, live_root=None):
    """Adapt + validate every run folder (and the live months under live_root); write one CSV per resource."""
    res, baselines = resources(), baseline_run_ids()
    tables = {name: [] for name in res}
    for root, kind in ((runs_root, None), (live_root, "live")):
        if not root or not os.path.isdir(root):
            continue
        for run_id in sorted(os.listdir(root)):
            run_dir = os.path.join(root, run_id)
            if os.path.exists(os.path.join(run_dir, "meta.json")):
                for name, rows in adapt(run_dir, baselines, kind=kind).items():
                    tables[name] += rows
    violations = {name: validate(name, rows) for name, rows in tables.items()}
    os.makedirs(out_dir, exist_ok=True)
    for name, rows in tables.items():
        cols = [f["name"] for f in res[name]["schema"]["fields"]]
        with open(os.path.join(out_dir, name + ".csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow(["" if r.get(c) is None else ("true" if r[c] is True else "false" if r[c] is False
                                                         else r[c]) for c in cols])
    return {name: len(rows) for name, rows in tables.items()}, violations


# ---------------------------------------------------------------- validator
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


def _type_ok(t, v):
    if t == "datetime":
        return isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v) is not None
    if t == "date":
        return isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) is not None
    if t in ("integer", "number") and isinstance(v, bool):
        return False
    return isinstance(v, _TYPES[t])


def validate(name, rows, schema=None):
    schema = schema or resources()[name]["schema"]
    fields = schema["fields"]
    names = [f["name"] for f in fields]
    bad, seen = [], set()
    for i, row in enumerate(rows):
        extra = set(row) - set(names)
        if extra:
            bad.append((i, ",".join(sorted(extra)), "not in contract"))
        for f in fields:
            v, c = row.get(f["name"]), f.get("constraints", {})
            if v is None or v == "" and f["type"] != "string":
                if c.get("required"):
                    bad.append((i, f["name"], "required"))
                continue
            if not _type_ok(f["type"], v):
                bad.append((i, f["name"], f"type {f['type']}: {v!r}"))
                continue
            if "enum" in c and v not in c["enum"]:
                bad.append((i, f["name"], f"enum: {v!r}"))
            if "pattern" in c and not re.fullmatch(c["pattern"], v):
                bad.append((i, f["name"], f"pattern: {v!r}"))
            if "minimum" in c and v < c["minimum"] or "maximum" in c and v > c["maximum"] \
                    or "exclusiveMinimum" in c and v <= c["exclusiveMinimum"]:
                bad.append((i, f["name"], f"bounds: {v!r}"))
        for a, op, b in schema.get("x-checks", []):
            if row.get(a) is not None and row.get(b) is not None and \
                    not (row[a] <= row[b] if op == "<=" else row[a] >= row[b]):
                bad.append((i, f"{a} {op} {b}", f"{row[a]} vs {row[b]}"))
        pk = tuple(row.get(k) for k in schema["primaryKey"])
        if pk in seen:
            bad.append((i, "+".join(schema["primaryKey"]), f"duplicate key {pk}"))
        seen.add(pk)
    return bad


# ---------------------------------------------------------------- DDL
def ddl():
    res = resources()
    out = []
    for r in res.values():
        s, cols = r["schema"], []
        for f in s["fields"]:
            c, parts = f.get("constraints", {}), [f'"{f["name"]}"' if f["name"] != f["name"].lower() else f["name"],
                                                    SQL_TYPE[f["type"]]]
            col = parts[0]
            if c.get("required"):
                parts.append("NOT NULL")
            checks = []
            if "enum" in c:
                vals = ", ".join(str(v) if f["type"] == "integer" else "'" + v + "'" for v in c["enum"] if v != "")
                checks.append(f"{col} IN ({vals})")
            if "pattern" in c:
                checks.append(f"{col} ~ '{c['pattern']}'")
            if "minimum" in c:
                checks.append(f"{col} >= {c['minimum']}")
            if "maximum" in c:
                checks.append(f"{col} <= {c['maximum']}")
            if "exclusiveMinimum" in c:
                checks.append(f"{col} > {c['exclusiveMinimum']}")
            if checks:
                parts.append("CHECK (" + " AND ".join(checks) + ")")
            cols.append("  " + " ".join(parts))
        cols.append("  PRIMARY KEY (" + ", ".join(s["primaryKey"]) + ")")
        for fk in s.get("foreignKeys", []):
            ref = res[fk["reference"]["resource"]]["x-table"]
            cols.append(f"  FOREIGN KEY ({', '.join(fk['fields'])}) REFERENCES {ref} "
                        f"({', '.join(fk['reference']['fields'])}) ON DELETE CASCADE")
        for a, op, b in s.get("x-checks", []):
            cols.append(f"  CHECK ({a} {op} {b})")
        out.append(f"CREATE TABLE {r['x-table']} (\n" + ",\n".join(cols) + "\n);")
    return "\n\n".join(out)
