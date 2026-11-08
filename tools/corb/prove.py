"""INF-P6: phase-prove gate for the L2 shadow layer (offline; nothing is wired).

report(family, data)     T01: one candidate against both baselines. Primary: the engine's P1obs stream, per asset
                         (full, W40, W80) and pooled (W250, W500), fires, skip rate, EF, E_N, AL, MaxDD, p_rand,
                         controls (evaluate.evaluate). Secondary: the same skips applied to the AOS-P3-REC runs
                         (baseline_lock.json "secondary") and to the six-asset portfolio replay (aos_portfolio).
stability(family, data)  T02: the verdict under +- one step of every §8.2 threshold that applies to the family, two
                         other seeds and a 5 / 10 day embargo; plus the size-only variant (half size instead of a
                         skip) as a sensitivity report.
Candidates: the three INF-P4 families, trained on the tape and on tape + replica history (INF-P4-T07).
"""
import copy
import csv
import json
import os

import aos_portfolio as ap
from corb import evaluate as ev
from corb.paths import INFRA, RUNS, TOOLS

CANDIDATES = [(f, d) for d in ("tester", "tester+replica") for f in ("cell_rule", "ridge_logit", "gbt")]
STEPS = {"cell_rule": [("cell_rule", "qualifying_n", 5), ("cell_rule", "bm_max", 0.02)],
         "ridge_logit": [("model_rule", "pred_e_max", 0.05), ("model_rule", "p_loss_min", 0.05)],
         "gbt": [("model_rule", "pred_e_max", 0.05), ("model_rule", "p_loss_min", 0.05)]}
COMMON_STEPS = [("skip_budget", "max_share_per_asset", 0.05)]
SEEDS = [20261107, 20261108]
EMBARGO = [5, 10]
STABLE_SHARE = 0.80


def _day(event_id):
    return event_id.rsplit("-", 1)[1]


def _vec(rs, cs, f):
    v = ev.vector(rs, cs)
    return v and dict(v, maxdd_pct=ev.maxdd_pct(rs, f))


def secondary(sd):
    """The candidate's skips applied to the AOS-P3-REC stream of each asset, on the same out-of-sample months."""
    with open(os.path.join(INFRA, "baseline_lock.json"), encoding="utf-8") as f:
        sec = json.load(f)["secondary"]["assets"]
    acc = ev.policy()["accept"]
    per, checks, pooled_b, pooled_k = {}, [], [], []
    for asset, g in sd[sd.role == "asset"].groupby("asset"):
        if asset not in sec:
            continue
        with open(os.path.join(RUNS, sec[asset]["run_id"], "events.csv"), encoding="utf-8") as f:
            events = sorted(csv.DictReader(f), key=lambda e: (_day(e["event_id"]), e["event_id"]))
        months = {m.replace("-", "") for m in g.month}
        base = [e for e in events if _day(e["event_id"])[:6] in months]
        skipped = set(g[g.verdict == "skip"].event_id)
        kept = [e for e in base if e["event_id"] not in skipped]
        fo = float(g.f_op.iloc[0])
        b = _vec([float(e["pnl_R"]) for e in base], [float(e["c_slip_R"]) for e in base], fo)
        k = _vec([float(e["pnl_R"]) for e in kept], [float(e["c_slip_R"]) for e in kept], fo)
        per[asset] = dict(run_id=sec[asset]["run_id"], n_base=len(base), n_kept=len(kept),
                          skipped_in_stream=len(base) - len(kept), base=b, kept=k)
        if b and k:
            checks.append(dict(name=f"secondary {asset} EF >= base - 1pp", ok=k["EF"] >= b["EF"] - acc["ef_slack"]))
            checks.append(dict(name=f"secondary {asset} MaxDD <= base + 2pp",
                               ok=k["maxdd_pct"] <= b["maxdd_pct"] + acc["maxdd_slack_pp"]))
        pooled_b += [(e, fo) for e in base]
        pooled_k += [(e, fo) for e in kept]
    pooled = {}
    for w in (250, 500):
        bb = sorted(pooled_b, key=lambda x: _day(x[0]["event_id"]))[-w:]
        kk = sorted(pooled_k, key=lambda x: _day(x[0]["event_id"]))[-w:]
        vb = ev.vector([float(e["pnl_R"]) for e, _ in bb], [float(e["c_slip_R"]) for e, _ in bb])
        vk = ev.vector([float(e["pnl_R"]) for e, _ in kk], [float(e["c_slip_R"]) for e, _ in kk])
        pooled[f"W{w}"] = dict(n_base=len(bb), base_EF=vb and vb["EF"], kept_EF=vk and vk["EF"],
                               base_E_N=vb and vb["E_N"], kept_E_N=vk and vk["E_N"])
        if vb and vk:
            checks.append(dict(name=f"secondary pooled W{w} EF >= base - 1pp", ok=vk["EF"] >= vb["EF"] - acc["ef_slack"]))
    return dict(per_asset=per, pooled=pooled, checks=checks)


def portfolio(skipped):
    """The six AOS-P3-REC streams on one account (aos_portfolio replay), with and without the candidate's skips."""
    with open(os.path.join(TOOLS, "aos_portfolio_streams.json"), encoding="utf-8") as f:
        spec = json.load(f)
    root = os.path.normpath(os.path.join(TOOLS, spec["runs_root"]))
    rows = []
    for key, s in spec["streams"].items():
        rows += ap.load_stream(key, os.path.join(root, s["run_id"]), s.get("bucket", ""))
    days = sorted(r["arm"] for r in rows)
    months = (days[-1] - days[0]).days / 30.44
    out = {}
    for label, rr in (("base", [dict(r) for r in rows]),
                      ("kept", [dict(r, filled=False, R=0.0) if r["id"] in skipped else dict(r) for r in rows])):
        _, rets, _, _ = ap.replay(rr)
        s = ap.stats(rets, label, months)
        out[label] = {k: s[k] for k in ("trades", "terminal", "maxdd", "mc2_p95dd", "ruin")}
    slack = ev.policy()["accept"]["maxdd_slack_pp"] / 100
    out["check"] = dict(name="portfolio MaxDD <= base + 2pp", ok=out["kept"]["maxdd"] <= out["base"]["maxdd"] + slack)
    return out


def _w500(sd):
    a = sd[sd.role == "asset"].sort_values(["local_day", "event_id"])
    kept = a[a.verdict == "fire"]
    vb, vk = ev.vector(a.y.tail(500), a.c_slip.tail(500)), ev.vector(kept.y.tail(500), kept.c_slip.tail(500))
    return dict(n_base=min(500, len(a)), base_EF=vb and vb["EF"], kept_EF=vk and vk["EF"])


def report(family, data):
    _, fl, sd, res = ev.candidate(family, data)
    skipped = set(sd[sd.verdict == "skip"].event_id)
    sec, port = secondary(sd), portfolio(skipped)
    w500 = _w500(sd)
    acc = ev.policy()["accept"]
    extra = sec["checks"] + [port["check"]]
    if res["pooled"]["withheld"]:
        extra.append(dict(name="primary pooled W500 EF >= base - 1pp",
                          ok=(w500["kept_EF"] or 0) >= (w500["base_EF"] or 0) - acc["ef_slack"]))
    per = {k: dict(role=v["role"], fires=v["n_kept"], n_base=v["n_base"], skip_rate=v["withheld"] / v["n_base"],
                   EF=[v["base"] and v["base"]["EF"], v["kept"] and v["kept"]["EF"]],
                   E_N=[v["base"] and v["base"]["E_N"], v["kept"] and v["kept"]["E_N"]],
                   AL=[v["base"] and v["base"]["AL"], v["kept"] and v["kept"]["AL"]],
                   W40_EF=[v["W40"]["base"], v["W40"]["kept"]], W80_EF=[v["W80"]["base"], v["W80"]["kept"]],
                   MaxDD_pct=[v["maxdd_base"], v["maxdd_kept"]], withheld_mean=v["withheld_mean"], p_rand=v["p_rand"])
           for k, v in res["per_asset"].items()}
    p = res["pooled"]
    gate_ok = res["verdict"] == "ACCEPT" and all(c["ok"] for c in extra)
    return dict(layer="L2 shadow", family=family, data=data, folds=len(fl), oos_months=[f[0] for f in fl],
                primary_verdict=res["verdict"], skips=res["pooled"]["withheld"],
                pooled=dict(n_base=p["n_base"], fires=p["n_kept"], skip_rate=p["withheld"] / p["n_base"],
                            W250_EF=[p["W250"]["base"], p["W250"]["kept"]], W500=w500,
                            E_N=[p["base"]["E_N"], p["kept"]["E_N"]], withheld_mean=p["withheld_mean"],
                            withheld_BM=p["withheld_BM"], p_rand=p["p_rand"]),
                per_asset=per, primary_failed=[c["name"] for c in res["checks"] if not c["ok"]],
                rejects=res["rejects"], secondary=sec, portfolio=port,
                extra_failed=[c["name"] for c in extra if not c["ok"]], gate_ok=gate_ok)


def _variants(family):
    base = ev.policy()
    out = []
    for section, key, step in STEPS[family] + COMMON_STEPS:
        for sign in (-1, 1):
            pol = copy.deepcopy(base)
            v = pol[section][key] + sign * step
            pol[section][key] = int(v) if isinstance(base[section][key], int) else round(v, 4)
            if section == "model_rule" and key == "pred_e_max":
                pol["model_rule"]["unsure_band"] = [pol["model_rule"]["pred_e_max"], 0.0]
            out.append((f"{section}.{key} {'+' if sign > 0 else '-'}{step}", pol, None, 0))
    out += [(f"seed {s}", base, s, 0) for s in SEEDS]
    out += [(f"embargo {d} days", base, None, d) for d in EMBARGO]
    return out


def size_only(sd):
    """Sensitivity: every would-skip traded at half size instead (R contribution x 0.5)."""
    a = sd[sd.role == "asset"].sort_values(["local_day", "event_id"])
    y = a.y.where(a.verdict == "fire", a.y * 0.5)
    vb, vh = ev.vector(a.y, a.c_slip), ev.vector(y, a.c_slip)
    f = float(a.f_op.median())
    return dict(E_N=[vb["E_N"], vh["E_N"]], EF=[vb["EF"], vh["EF"]], E=[vb["E"], vh["E"]],
                MaxDD_pct=[ev.maxdd_pct(list(a.y), f), ev.maxdd_pct(list(y), f)])


def stability(family, data):
    _, _, sd0, res0 = ev.candidate(family, data)
    base_verdict = res0["verdict"]
    rows = []
    seed0 = ev.SEED
    for label, pol, seed, embargo in _variants(family):
        try:
            if seed:
                ev.SEED = seed
            _, _, sd, res = ev.candidate(family, data, pol=pol, embargo_days=embargo)
        finally:
            ev.SEED = seed0
        p = res["pooled"]
        rows.append(dict(variant=label, verdict=res["verdict"], skips=p["withheld"], withheld_mean=p["withheld_mean"],
                         p_rand=p["p_rand"]))
    same = sum(r["verdict"] == base_verdict for r in rows) / len(rows)
    return dict(family=family, data=data, base_verdict=base_verdict, variants=rows, same_share=same,
                stable=same >= STABLE_SHARE, any_accept=[r["variant"] for r in rows if r["verdict"] == "ACCEPT"],
                size_only=size_only(sd0))
