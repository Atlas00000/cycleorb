"""INF-P4: offline train + evaluation harness. L2 runs in SHADOW only: nothing here is wired into the EA.

dataset      the P1obs tape (filled armed days; label y = the engine's exact shadow outcome), dataset_id = its sha256
folds        anchored monthly walk-forward (train on every month before t, score month t), optional embargo, and a
             decay guard: training that reaches into a known decay window must hold >= 6 earlier months (T02)
families     engine (fire everything), cell_rule (T03), ridge_logit and gbt (T05), all under the pre-registered
             low bar in infra/policy_low_bar.json and its 15 % skip budget per asset
evaluate     counterfactual blotter (the engine minus would-skips) scored with framework numbers per asset and pooled,
             skip precision vs random skips, payoff trap, controls, frequency (T01, T06) -> verdict per §8.1
registry     train.dataset, train.model_version (never overwritten), score.eval_run, score.shadow_decision (T04)
regression   the harness must reproduce the recorded AOS-P4 walk-forward and AOS-P2 verdicts (T01)
"""
import csv
import hashlib
import json
import math
import os
import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

import aos_gate_wf as gw
import corb_metrics as cm
from corb import db
from corb.inventory import sha256
from corb.paths import INFRA, REPO, TOOLS, VAR, git_info
from corb.regime import _band, _vol_tercile

TAPE = os.path.join(REPO, "tester", "aos", "tape", "tape_P1obs.csv")
POLICY = os.path.join(INFRA, "policy_low_bar.json")
ARTEFACTS = os.path.join(VAR, "artefacts")
SEED = 20261106
DECAY = {"DE40": "2026-09", "EURUSD-LON0700": "2026-01"}   # edge_framework.md decay windows (start month)
FAMILIES = ["engine", "cell_rule", "ridge_logit", "gbt"]


def policy():
    with open(POLICY, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- dataset
def load():
    df = gw.load(TAPE)
    df["y_actual"] = pd.to_numeric(df["actual_R"], errors="coerce").fillna(df["y"])
    slip = {}
    for ln in db.psql("""SELECT e.event_id, e."c_slip_prior_R" FROM core.event e JOIN core.run r USING (run_key)
                         WHERE r.ea_version = '1.11' AND r.run_tag = 'P1obs';""").splitlines():
        eid, v = ln.split("\t")
        slip[eid] = float(v) if v else None
    df["c_slip"] = df["event_id"].map(slip)
    df["c_slip"] = df["c_slip"].fillna(df.groupby("asset")["c_slip"].transform("median"))
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        f_op = {k: v["f_op"] for k, v in json.load(f)["assets"].items()}
    df["f_op"] = df["asset"].map(f_op)
    return df


def dataset_info(df):
    return dict(dataset_id=sha256(TAPE)[:16], source=os.path.relpath(TAPE, REPO).replace("\\", "/"), rows=len(df),
                label="shadow_R of filled armed days (P1obs, v1.11)",
                window_from=df.local_day.min().replace(".", "-"), window_to=df.local_day.max().replace(".", "-"),
                sha256=sha256(TAPE))


# ---------------------------------------------------------------- T02 folds
def folds(df, min_train=gw.MIN_TRAIN, embargo_days=0):
    out = []
    for m in sorted(df.month.unique()):
        train = df[(df.month < m) & (df.role == "asset")]
        if embargo_days:
            cut = pd.Timestamp(m + "-01") - pd.Timedelta(days=embargo_days)
            train = train[pd.to_datetime(train.local_day.str.replace(".", "-", regex=False)) < cut]
        test = df[df.month == m]
        if len(train) >= min_train and not test.empty:
            out.append((m, train.index, test.index))
    return out


def decay_guard_ok(train):
    """Training that reaches into an asset's decay window must hold >= 6 months before it (never fit on decay only)."""
    for asset, start in DECAY.items():
        t = train[train.asset == asset]
        if len(t) and (t.month >= start).any() and t[t.month < start].month.nunique() < 6:
            return False
    return True


# ---------------------------------------------------------------- T03 cell rule
def _cells_of(row, cuts):
    return dict(range_atr=_band(row.atr_pct, *cuts[row.asset]) if row.asset in cuts and pd.notna(row.atr_pct) else None,
                vol_tercile=_vol_tercile(row.vol_pct) if pd.notna(row.vol_pct) else None,
                trend_side=None if pd.isna(row.trend_side) else str(int(row.trend_side)),
                event_in_hold=None if pd.isna(row.ev_tier1_hold) else ("yes" if row.ev_tier1_hold > 0 else "no"))


def fit_cells(train, pol):
    cuts = {}
    for a, g in train.groupby("asset"):
        x = sorted(g.atr_pct.dropna())
        if len(x) >= 3:
            cuts[a] = (x[len(x) // 3], x[2 * len(x) // 3])
    groups = {}
    for row in train.itertuples():
        for dim, val in _cells_of(row, cuts).items():
            if val is not None and dim in pol["cell_rule"]["dims"]:
                groups.setdefault((row.asset, dim, val), []).append((row.y_actual, row.y))
    neg = {}
    for key, pairs in groups.items():
        if len(pairs) < pol["cell_rule"]["qualifying_n"]:
            continue
        ba, bs = cm.core([p[0] for p in pairs])["BM"], cm.core([p[1] for p in pairs])["BM"]
        if ba is not None and bs is not None and ba <= pol["cell_rule"]["bm_max"] and bs <= pol["cell_rule"]["bm_max"]:
            neg[key] = (ba, len(pairs))
    return cuts, neg


# ---------------------------------------------------------------- T05 models
def make_models(family):
    if family == "ridge_logit":
        return Ridge(alpha=30.0), LogisticRegression(C=0.1, max_iter=2000)
    return (HistGradientBoostingRegressor(max_depth=2, max_iter=150, learning_rate=0.04, min_samples_leaf=30,
                                          l2_regularization=1.0, random_state=SEED),
            HistGradientBoostingClassifier(max_depth=2, max_iter=150, learning_rate=0.04, min_samples_leaf=30,
                                           l2_regularization=1.0, random_state=SEED))


def fit_predict(family, train, test, assets):
    xtr, xte = gw.design(train, test, assets)
    mu, sd = xtr.mean(), xtr.std().replace(0, 1.0)
    reg, clf = make_models(family)
    reg.fit((xtr - mu) / sd, train.y)
    clf.fit((xtr - mu) / sd, (train.y < 0).astype(int))
    return reg.predict((xte - mu) / sd), clf.predict_proba((xte - mu) / sd)[:, 1], (reg, clf, mu, sd, list(xtr.columns))


# ---------------------------------------------------------------- shadow decisions
def shadow(df, family, pol, fold_list):
    assets = sorted(df[df.role == "asset"].asset.unique())
    rows, guard_refusals = [], 0
    for m, tr_idx, te_idx in fold_list:
        train, test = df.loc[tr_idx], df.loc[te_idx]
        guard = decay_guard_ok(train)
        guard_refusals += not guard
        pred_e = p_loss = [None] * len(test)
        neg, cuts = {}, {}
        if guard and family == "cell_rule":
            cuts, neg = fit_cells(train, pol)
        elif guard and family in ("ridge_logit", "gbt"):
            pred_e, p_loss, _ = fit_predict(family, train, test, assets)
        for i, row in enumerate(test.itertuples()):
            r = dict(event_id=row.event_id, asset=row.asset, role=row.role, month=m, local_day=row.local_day,
                     y=row.y, y_actual=row.y_actual, c_slip=row.c_slip, f_op=row.f_op, pred_e=None, p_loss=None,
                     verdict="fire", reason_code="ALLOW_DEFAULT", detail="", severity=0.0)
            if not guard:
                r["reason_code"] = "ALLOW_GUARD_DECAY"
            elif family == "cell_rule":
                hits = [(neg[(row.asset, d, v)][0], f"{d}={v}") for d, v in _cells_of(row, cuts).items()
                        if (row.asset, d, v) in neg]
                if hits:
                    bm, label = min(hits)
                    r.update(verdict="skip", reason_code="SKIP_CELL_BM_NEG", detail=f"{label} BM {100 * bm:+.1f}pp",
                             severity=-bm)
            elif family in ("ridge_logit", "gbt"):
                e, p = float(pred_e[i]), float(p_loss[i])
                r.update(pred_e=e, p_loss=p)
                mr = pol["model_rule"]
                if e <= mr["pred_e_max"] and p >= mr["p_loss_min"]:
                    r.update(verdict="skip", reason_code="SKIP_MODEL_LOSER", severity=-e)
                elif mr["unsure_band"][0] < e <= mr["unsure_band"][1]:
                    r["reason_code"] = "ALLOW_UNSURE"
            rows.append(r)
    return apply_budget(pd.DataFrame(rows), pol), guard_refusals


def apply_budget(sd, pol):
    """Skip budget: per asset, keep the most severe skips up to the cap; the rest fire as ALLOW_BUDGET_CAP."""
    cap = pol["skip_budget"]["max_share_per_asset"]
    for _, g in sd.groupby("asset"):
        sk = g[g.verdict == "skip"].sort_values("severity", ascending=False)
        allowed = math.floor(cap * len(g))
        if len(sk) > allowed:
            sd.loc[sk.index[allowed:], ["verdict", "reason_code"]] = ["fire", "ALLOW_BUDGET_CAP"]
    return sd


# ---------------------------------------------------------------- T01 / T06 evaluation
def vector(y, c_slip):
    y = list(y)
    if len(y) < 2:
        return None
    c = cm.core(y)
    if c["R"] is None:
        return dict(n=c["n"], E=c["E"], WR=c["WR"], R=None, AL=None, E_N=None, EF=None, M=None, worst=min(y))
    lk = cm.leak(float(np.mean(c_slip)), c["R"])
    return dict(n=c["n"], E=c["E"], WR=c["WR"], R=c["R"], AL=c["AL"], E_N=c["E_N"], EF=c["BM"] - lk,
                M=cm.wilson_half(c["WR"], c["n"]), worst=min(y))


def maxdd_pct(y, f):
    return 100 * cm.max_drawdown([f * r for r in y]) if len(y) else 0.0


def p_rand(y_all, withheld_mean, k, seed):
    if k == 0:
        return None
    rng = np.random.default_rng(seed)
    y = np.asarray(y_all)
    draws = np.array([y[rng.choice(len(y), k, replace=False)].mean() for _ in range(2000)])
    return float((draws <= withheld_mean).mean())


def evaluate(sd, pol):
    acc = pol["accept"]
    sd = sd.sort_values(["local_day", "event_id"]).reset_index(drop=True)
    per, checks, rejects, warns = {}, [], [], []
    for a, g in sd.groupby("asset"):
        kept, held = g[g.verdict == "fire"], g[g.verdict == "skip"]
        base_v, kept_v = vector(g.y, g.c_slip), vector(kept.y, kept.c_slip)
        w = {n: (vector(g.y.tail(n), g.c_slip.tail(n)), vector(kept.y.tail(n), kept.c_slip.tail(n))) for n in (40, 80)}
        f = float(g.f_op.iloc[0])
        hb = cm.core(list(held.y)) if len(held) > 1 else None
        per[a] = dict(role=g.role.iloc[0], n_base=len(g), n_kept=len(kept), withheld=len(held),
                      retention=len(kept) / len(g), base=base_v, kept=kept_v,
                      W40=dict(base=w[40][0] and w[40][0]["EF"], kept=w[40][1] and w[40][1]["EF"]),
                      W80=dict(base=w[80][0] and w[80][0]["EF"], kept=w[80][1] and w[80][1]["EF"]),
                      maxdd_base=maxdd_pct(list(g.y), f), maxdd_kept=maxdd_pct(list(kept.y), f),
                      withheld_mean=float(held.y.mean()) if len(held) else None,
                      withheld_BM=hb["BM"] if hb else None,
                      p_rand=p_rand(g.y, float(held.y.mean()), len(held), SEED) if len(held) else None,
                      reasons=g.reason_code.value_counts().to_dict())
    assets = sd[sd.role == "asset"]
    kept, held = assets[assets.verdict == "fire"], assets[assets.verdict == "skip"]
    hb = cm.core(list(held.y)) if len(held) > 1 else None
    pooled = dict(n_base=len(assets), n_kept=len(kept), withheld=len(held), base=vector(assets.y, assets.c_slip),
                  kept=vector(kept.y, kept.c_slip),
                  W250=dict(base=vector(assets.y.tail(250), assets.c_slip.tail(250))["EF"],
                            kept=vector(kept.y.tail(250), kept.c_slip.tail(250))["EF"]),
                  withheld_mean=float(held.y.mean()) if len(held) else None, withheld_BM=hb["BM"] if hb else None,
                  p_rand=p_rand(assets.y, float(held.y.mean()), len(held), SEED) if len(held) else None)

    def chk(name, ok, detail=""):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    controls = [k for k, v in per.items() if v["role"] == "control"]
    if not controls:
        rejects.append("negative controls missing from the evaluation (fail closed)")
    for k in controls:
        ef = per[k]["kept"] and per[k]["kept"]["EF"]
        chk(f"control {k} EF <= 0", ef is None or ef <= 0, f"EF {ef}")
    if len(held) == 0:
        verdict = "ACCEPT" if not rejects else "REJECT"
        return dict(verdict=verdict, note="no skips: the engine is unchanged (no harm, nothing to remove)",
                    per_asset=per, pooled=pooled, checks=checks, rejects=rejects, warnings=warns)
    pb, pk = pooled["base"], pooled["kept"]
    chk("pooled n kept >= 100", pooled["n_kept"] >= acc["pooled_n_min"])
    if pooled["n_kept"] < acc["pooled_n_warn"]:
        warns.append(f"pooled n kept {pooled['n_kept']} < {acc['pooled_n_warn']} (evidence label, not a gate)")
    chk("pooled W250 EF >= base - 1pp", pooled["W250"]["kept"] >= pooled["W250"]["base"] - acc["ef_slack"])
    improved = pk["AL"] < pb["AL"] or pk["worst"] > pb["worst"]
    chk("pooled E_N up, or held with a risk improvement",
        pk["E_N"] > pb["E_N"] or (abs(pk["E"] - pb["E"]) <= acc["e_hold"] and improved))
    if pk["WR"] > pb["WR"] and pk["E_N"] < pb["E_N"]:
        rejects.append("payoff trap: WR up, E_N down (pooled)")
    for k, v in per.items():
        if v["role"] != "asset" or not v["kept"] or not v["base"]:
            continue
        chk(f"{k} full EF >= base - 1pp", (v["kept"]["EF"] or 0) >= (v["base"]["EF"] or 0) - acc["ef_slack"])
        if v["W80"]["base"] is not None and v["W80"]["kept"] is not None:
            chk(f"{k} W80 EF >= base - 1pp", v["W80"]["kept"] >= v["W80"]["base"] - acc["ef_slack"])
        chk(f"{k} E loss <= 0.05R", v["kept"]["E"] >= v["base"]["E"] - acc["asset_e_loss_max"])
        chk(f"{k} MaxDD <= base + 2pp", v["maxdd_kept"] <= v["maxdd_base"] + acc["maxdd_slack_pp"])
        if v["retention"] < acc["fire_stall"]:
            rejects.append(f"{k}: FREQUENCY_STALL, fire retention {v['retention']:.0%}")
        elif v["retention"] < acc["fire_warn"]:
            warns.append(f"{k}: fire retention {v['retention']:.0%} < 70 %")
    chk("skip precision: withheld mean R < 0", pooled["withheld_mean"] < 0, f"{pooled['withheld_mean']:+.3f}R")
    chk("skip precision: withheld BM <= 0", pooled["withheld_BM"] is not None and pooled["withheld_BM"] <= 0)
    chk("skip precision: p_rand <= 0.20", pooled["p_rand"] <= acc["p_rand_max"], f"p_rand {pooled['p_rand']:.2f}")
    verdict = "REJECT" if rejects else ("ACCEPT" if all(c["ok"] for c in checks) else "NOT ACCEPTED")
    return dict(verdict=verdict, per_asset=per, pooled=pooled, checks=checks, rejects=rejects, warnings=warns)


# ---------------------------------------------------------------- T04 registry
def _code_sha():
    return sha256(os.path.abspath(__file__))[:16]


def register(df, family, pol, sd, result, fold_list, recipe, info=None):
    info = info or dataset_info(df)
    params = dict(engine={}, cell_rule=pol["cell_rule"],
                  ridge_logit=dict(reg="Ridge(alpha=30)", clf="LogisticRegression(C=0.1)", rule=pol["model_rule"]),
                  gbt=dict(reg="HGBRegressor(depth2,150,lr.04,leaf30,l2=1)", clf="HGBClassifier(same)",
                           rule=pol["model_rule"]))[family]
    features = pol["cell_rule"]["dims"] if family == "cell_rule" else (gw.NUM if family != "engine" else [])
    pol_sha = sha256(POLICY)
    ident = json.dumps(dict(family=family, params=params, features=features, dataset=info["dataset_id"],
                            policy=pol_sha, code=_code_sha()), sort_keys=True)
    sha8 = hashlib.sha256(ident.encode()).hexdigest()[:8]
    semver = f"l2-{family.replace('_', '')}-1.0.0+{sha8}"
    os.makedirs(os.path.join(ARTEFACTS, "models"), exist_ok=True)
    art = os.path.join(ARTEFACTS, "models", semver + ".pkl")
    assets_rows = df[df.role == "asset"]
    if family in ("ridge_logit", "gbt"):
        _, _, model = fit_predict(family, assets_rows, assets_rows, sorted(assets_rows.asset.unique()))
        blob = model
    elif family == "cell_rule":
        blob = fit_cells(assets_rows, pol)
    else:
        blob = None
    with open(art, "wb") as f:
        pickle.dump(blob, f)
    status = "candidate" if result["verdict"] == "ACCEPT" and family != "engine" else (
        "champion" if family == "engine" else "shelved")
    eval_id = hashlib.sha256(f"{recipe}:{semver}:{info['dataset_id']}:{SEED}".encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    q = lambda s: "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"
    sql = [
        "BEGIN;",
        f"INSERT INTO train.dataset VALUES ({q(info['dataset_id'])}, {q(info['source'])}, {info['rows']}, "
        f"{q(info['label'])}, {q(info['window_from'])}, {q(info['window_to'])}, {q(info['sha256'])}, {q(now)}) "
        "ON CONFLICT DO NOTHING;",
        f"INSERT INTO train.model_version VALUES ({q(semver)}, {q(family)}, {q(json.dumps(params))}::jsonb, "
        f"{q(json.dumps(features))}::jsonb, {q(info['dataset_id'])}, {q(pol_sha)}, "
        f"{q(os.path.relpath(art, VAR).replace(chr(92), '/'))}, {q(sha256(art))}, {q(status)}, {q(now)}, NULL) "
        "ON CONFLICT DO NOTHING;",
        f"DELETE FROM score.eval_run WHERE eval_id = {q(eval_id)};",
        f"INSERT INTO score.eval_run VALUES ({q(eval_id)}, {q(recipe)}, {q(semver)}, {q(info['dataset_id'])}, "
        f"{len(fold_list)}, {SEED}, {q(git_info()['head'])}, {q(result['verdict'])}, "
        f"{q('var/scorecards/' + recipe + '.json')}, {q(now)});",
    ]
    stage = os.path.join(VAR, "stage", "shadow_decision.csv")
    os.makedirs(os.path.dirname(stage), exist_ok=True)
    cols = ["eval_id", "event_id", "asset", "role", "month", "verdict", "reason_code", "pred_e", "p_loss", "detail", "y"]
    with open(stage, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in sd.itertuples():
            w.writerow([eval_id, r.event_id, r.asset, r.role, r.month, r.verdict, r.reason_code,
                        "" if r.pred_e is None or pd.isna(r.pred_e) else r.pred_e,
                        "" if r.p_loss is None or pd.isna(r.p_loss) else r.p_loss, r.detail, r.y])
    sql += [f"\\copy score.shadow_decision ({', '.join(cols)}) FROM '/corb/var/stage/shadow_decision.csv' "
            "WITH (FORMAT csv, HEADER true)", "COMMIT;"]
    db.psql("\n".join(sql) + "\n")
    return dict(model_semver=semver, eval_id=eval_id, status=status, artefact=os.path.relpath(art, REPO))


def run(family, embargo_days=0):
    pol, df = policy(), load()
    fl = folds(df, embargo_days=embargo_days)
    sd, refusals = shadow(df, family, pol, fl)
    result = evaluate(sd, pol)
    task = {"engine": "T05", "cell_rule": "T03", "ridge_logit": "T05", "gbt": "T05"}[family]
    recipe = f"INF-P4-{task}_train_L2shadow_{family}_2025-07_2026-10"
    reg = register(df, family, pol, sd, result, fl, recipe)
    skip_clusters = sd[sd.verdict == "skip"].groupby(["asset", "month", "reason_code"]).size().reset_index(name="n")
    result.update(recipe=recipe, folds=len(fl), oos_months=[f[0] for f in fl], guard_refusals=refusals,
                  dataset=dataset_info(df), policy_sha256=sha256(POLICY), registry=reg,
                  skip_clusters=skip_clusters.to_dict("records"),
                  skipped=sd[sd.verdict == "skip"][["event_id", "asset", "month", "reason_code", "detail", "y"]]
                  .to_dict("records"))
    return result


# ---------------------------------------------------------------- T07 data gain (replica history, training only)
def replica_rows():
    """The production assets' replica-extended events (INF-P3-T07 extend) as tape rows: y = the replica's pnl_R,
    features from the offline builder on the same UTC bars. Context-symbol and spread_live features are missing
    (median-filled by design()); calendar features are missing before the calendar snapshot starts (2025-01)."""
    import glob as _glob
    from datetime import date as _date
    from corb import featbuild, replica
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    rows, sources = [], []
    for asset in replica.EXTEND:
        a = assets[asset]
        if a.get("role") == "control":
            continue
        for d in _glob.glob(os.path.join(replica.OUT, "runs", "replica_*")):
            with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("native_run") != a["run_id"]:
                continue
            inputs, setup = meta["inputs"], meta["setups"][0]
            ccys = {c.strip() for c in (inputs.get("InpAosEventCcy") or "").split(",") if c.strip()}
            cal = featbuild.load_events(ccys) if ccys else []
            cal_start = datetime.fromtimestamp(cal[0][0], timezone.utc).date() if cal else None
            bars, cache = replica.utc_bars(meta["symbol"], meta["clock_offsets"]), {}
            with open(os.path.join(d, "events.csv"), encoding="utf-8") as f:
                events = list(csv.DictReader(f))
            sources.append(sha256(os.path.join(d, "events.csv")))
            for e in events:
                day = _date.fromisoformat(e["day"])
                feats = featbuild.build_day(bars, [], cal if cal_start and day >= cal_start else None, inputs, setup,
                                            day, float(meta["point"]), cache)
                rows.append(dict(asset=asset, role="asset", setup=setup, local_day=day.strftime("%Y.%m.%d"),
                                 month=day.strftime("%Y-%m"), event_id=e["event_id"], y=float(e["pnl_R"]),
                                 y_actual=float(e["pnl_R"]), c_slip=float(e["c_slip_R"]), f_op=a["f_op"],
                                 source="replica", **{k: v for k, v in feats.items() if k in gw.NUM}))
    df = pd.DataFrame(rows)
    df["spread_ratio"] = np.nan
    if "ev_next_min" in df:
        df["ev_next_min"] = df["ev_next_min"].where(df["ev_next_min"] >= 0, 1440)
    for c in gw.NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    digest = hashlib.sha256(("".join(sorted(sources)) + sha256(TAPE)).encode()).hexdigest()
    return df, digest


_DATA = {}


def datasets(with_replica=False):
    """The tape (and, on request, tape + replica history), loaded once per process."""
    if "base" not in _DATA:
        base = load()
        base["source"] = "tester"
        _DATA.update(base=base, months=[f[0] for f in folds(base)])
    if with_replica and "ext" not in _DATA:
        base = _DATA["base"]
        rep, digest = replica_rows()
        ext = pd.concat([base, rep], ignore_index=True).sort_values(["local_day", "event_id"]).reset_index(drop=True)
        info = dict(dataset_info(base), dataset_id=digest[:16], rows=len(ext),
                    source="tape_P1obs.csv + replica-extended production assets (INF-P3-T07, training only)",
                    label="tester: shadow_R; replica: replica pnl_R", window_from=ext.local_day.min().replace(".", "-"),
                    sha256=digest)
        _DATA.update(ext=ext, rep=rep, info=info)
    return _DATA


def candidate(family, data="tester", pol=None, embargo_days=0):
    """Shadow decisions + evaluation of one family on the P4 out-of-sample months, test rows = tester rows only.
    data: 'tester' (the tape) or 'tester+replica' (tape + replica history in training)."""
    c = datasets(with_replica=data != "tester")
    pol = pol or policy()
    df = c["base"] if data == "tester" else c["ext"]
    fl = [(m, tr, df.loc[te][df.loc[te].source == "tester"].index)
          for m, tr, te in folds(df, embargo_days=embargo_days) if m in c["months"]]
    sd, _ = shadow(df, family, pol, fl)
    return df, fl, sd, evaluate(sd, pol)


def data_gain(families=("cell_rule", "ridge_logit", "gbt")):
    """Same protocol, same out-of-sample months (the P4 folds), test rows = tester rows only; training either the
    tester tape alone or tape + replica history. Acceptance stays the §8.1 bar on tester months."""
    pol = policy()
    c = datasets(with_replica=True)
    info, rep, months = c["info"], c["rep"], c["months"]
    out = dict(replica_rows=len(rep), replica_by_asset=rep.groupby("asset").size().to_dict(), oos_months=months,
               results={})
    for name in ("tester", "tester+replica"):
        for fam in families:
            df, fl, sd, res = candidate(fam, name, pol)
            p = res["pooled"]
            row = dict(verdict=res["verdict"], train_rows_first_fold=int(len(fl[0][1])) if fl else 0,
                       withheld=p["withheld"], n_base=p["n_base"], withheld_mean=p["withheld_mean"],
                       p_rand=p["p_rand"], E_N=[p["base"]["E_N"], p["kept"]["E_N"]],
                       failed=[c["name"] for c in res["checks"] if not c["ok"]], rejects=res["rejects"])
            if name == "tester+replica":
                recipe = f"INF-P4-T07_train_L2shadow_dataGain_{fam}"
                row["registry"] = register(df, fam, pol, sd, res, fl, recipe, info=info)
            out["results"][f"{name}:{fam}"] = row
    return out


# ---------------------------------------------------------------- T01 regression
def regression():
    """The harness's evaluation code must reproduce the recorded AOS-P4 walk-forward (the original protocol's
    folds and models, scored by evaluate()'s functions) and the recorded AOS-P2 verdicts."""
    from aos_compare import _ledger_mult, compare
    from corb_bench import load_run
    out = []
    df = gw.load(TAPE)
    assets = sorted(df[df.role == "asset"].asset.unique())
    for retain, path in ((0.70, "p4_walkforward.json"), (0.90, "p4_walkforward_r90.json")):
        with open(os.path.join(REPO, "tester", "aos", path), encoding="utf-8") as f:
            rec = {(r["model"], r["asset"]): r for r in json.load(f)}
        gw.RETAIN = retain
        for name, make in gw.models().items():
            oos = gw.walk_forward(df, assets, name, make)
            g = oos[oos.role == "asset"]
            held = g[g.withhold]
            want = rec[(name, "POOLED")]
            got = dict(n=len(g), withheld=len(held), withheld_meanR=float(held.y.mean()),
                       E_kept=float(g[~g.withhold].y.mean()),
                       p_vs_random=p_rand(g.y, float(held.y.mean()), len(held), SEED))
            for k in ("n", "withheld", "withheld_meanR", "E_kept"):
                out.append(dict(name=f"AOS-P4 {name} retain {retain:.0%} {k}", expected=want[k], got=got[k],
                                ok=abs(got[k] - want[k]) <= 1e-9))
            out.append(dict(name=f"AOS-P4 {name} retain {retain:.0%} p_rand (MC, ±0.05)", expected=want["p_vs_random"],
                            got=got["p_vs_random"], ok=abs(got["p_vs_random"] - want["p_vs_random"]) <= 0.05))
    gw.RETAIN = 0.70
    with open(os.path.join(REPO, "tester", "aos", "p2_compare.json"), encoding="utf-8") as f:
        p2 = json.load(f)
    runs = os.path.join(REPO, "tester", "aos", "runs")
    for rec in p2["pairs"]:
        b, v = os.path.join(runs, rec["base"]), os.path.join(runs, rec["variant"])
        if not (os.path.isdir(b) and os.path.isdir(v)):
            continue
        r = compare(*load_run(b), *load_run(v), var_mult=_ledger_mult(v))
        out.append(dict(name=f"AOS-P2 {rec['variant'][-6:]} verdict", expected=rec["verdict"], got=r["verdict"],
                        ok=r["verdict"] == rec["verdict"]))
        out.append(dict(name=f"AOS-P2 {rec['variant'][-6:]} withheld mean R", expected=rec["withheld"]["mean_R"],
                        got=r["withheld"]["mean_R"], ok=rec["withheld"]["mean_R"] == r["withheld"]["mean_R"] or
                        abs((rec["withheld"]["mean_R"] or 0) - (r["withheld"]["mean_R"] or 0)) <= 1e-9))
    return out
