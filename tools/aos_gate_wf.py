"""AOS-P4-T01..T03, T05..T07 (offline): pooled learned gate, anchored monthly walk-forward.

Label: shadow_R of each armed setup-day that the engine would have filled (exact engine outcome, P1).
Features: decision-time L1 features, asset one-hot, session one-hot; per-asset scaling fitted on training data only.
Walk-forward: for each month t (once >= MIN_TRAIN training events exist), train on all months < t, score month t.
Gate: withhold a day when its prediction is below the asset's in-sample 30th percentile (target retention ~70 %),
size variant: the same days at 0.5x. Controls (AAPL / MSFT / XOM) are never trained on, only scored.

Usage:  python aos_gate_wf.py [--tape ../tester/aos/tape/tape_P1obs.csv] [--json out.json]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

import corb_metrics as cm

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_TRAIN = 250
RETAIN = 0.70
SEED = 20261106
NUM = ["atr_pct", "cost_pct", "vol_pct", "trend_side", "gap_atr", "pre_drift_atr", "range_pos_prev", "brk_prev_high",
       "brk_prev_low", "inside_prev", "outside_prev", "nr4", "nr7", "sma_dist_hi_atr", "sma_dist_lo_atr", "dow",
       "ev_tier1_entry", "ev_tier1_hold", "ev_next_min", "opex", "quad_witching", "ctx1_prevday_atr",
       "ctx1_lookback_atr", "ctx2_prevday_atr", "ctx2_lookback_atr", "spread_ratio"]
PER_ASSET_Z = ["atr_pct", "cost_pct", "spread_ratio"]


def load(tape):
    df = pd.read_csv(tape, low_memory=False)
    df = df[df["shadow_status"] == "FILLED"].copy()
    df["y"] = df["shadow_R"].astype(float)
    df["month"] = df["local_day"].str[:7].str.replace(".", "-", regex=False)
    df["spread_ratio"] = df["spread_live_pt"] / df["spread_avg_pt"].replace(0, np.nan)
    df["ev_next_min"] = df["ev_next_min"].where(df["ev_next_min"] >= 0, 1440)
    for c in NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("local_day").reset_index(drop=True)


def design(train, test, assets):
    """Per-asset z-scores and medians from the training rows only; asset / session one-hot."""
    tr, te = train[NUM].copy(), test[NUM].copy()
    for c in PER_ASSET_Z:
        for a in assets:
            m, s = train.loc[train.asset == a, c].mean(), train.loc[train.asset == a, c].std()
            s = s if s and s > 0 else 1.0
            tr.loc[train.asset == a, c] = (train.loc[train.asset == a, c] - m) / s
            te.loc[test.asset == a, c] = (test.loc[test.asset == a, c] - m) / s
    med = tr.median()
    tr, te = tr.fillna(med).fillna(0.0), te.fillna(med).fillna(0.0)
    for a in assets:
        tr["a_" + a], te["a_" + a] = (train.asset == a).astype(float), (test.asset == a).astype(float)
    for s in ("LON", "NY", "TKY"):
        tr["s_" + s], te["s_" + s] = (train.setup == s).astype(float), (test.setup == s).astype(float)
    return tr, te


def models():
    return {
        "ridge": lambda: Ridge(alpha=30.0),
        "gbt": lambda: HistGradientBoostingRegressor(max_depth=2, max_iter=150, learning_rate=0.04,
                                                     min_samples_leaf=30, l2_regularization=1.0, random_state=SEED),
    }


def walk_forward(df, assets, name, make):
    months = sorted(df.month.unique())
    out = []
    for m in months:
        train = df[(df.month < m) & (df.role == "asset")]
        test = df[df.month == m]
        if len(train) < MIN_TRAIN or test.empty:
            continue
        xtr, xte = design(train, test, assets)
        mu, sd = xtr.mean(), xtr.std().replace(0, 1.0)
        model = make().fit((xtr - mu) / sd, train.y)
        p_tr = model.predict((xtr - mu) / sd)
        p_te = model.predict((xte - mu) / sd)
        thr = {a: np.quantile(p_tr[train.asset.values == a], 1 - RETAIN) for a in assets}
        t = test.copy()
        t["pred"] = p_te
        # controls use the pooled threshold (never trained on)
        pooled_thr = np.quantile(p_tr, 1 - RETAIN)
        t["withhold"] = [p < thr.get(a, pooled_thr) for p, a in zip(p_te, t.asset)]
        t["model"] = name
        out.append(t)
    return pd.concat(out) if out else pd.DataFrame()


def summarise(oos, label, rng):
    rows = []
    for key, g in [("POOLED", oos[oos.role == "asset"])] + [(a, oos[oos.asset == a]) for a in sorted(oos.asset.unique())]:
        if g.empty:
            continue
        y, w = g.y.values, g.withhold.values
        kept, held = y[~w], y[w]
        c_all, c_kept = cm.core(list(y)), cm.core(list(kept)) if len(kept) > 5 else None
        c_held = cm.core(list(held)) if len(held) > 5 else None
        # random-skip baseline: same number withheld at random, 2000 draws
        k = int(w.sum())
        rnd = np.array([y[rng.choice(len(y), k, replace=False)].mean() for _ in range(2000)]) if k else np.array([0.0])
        p_rand = float((rnd <= (held.mean() if k else 0)).mean())
        size_sum = kept.sum() + 0.5 * held.sum()
        rows.append(dict(model=label, asset=key, role=g.role.iloc[0], n=len(y), withheld=k,
                         retention=1 - k / len(y), E_all=y.mean(), E_kept=kept.mean() if len(kept) else None,
                         withheld_meanR=held.mean() if k else None,
                         withheld_BM=c_held["BM"] if c_held and c_held["BM"] is not None else None,
                         p_vs_random=p_rand, sum_all=y.sum(), sum_kept=kept.sum(), sum_size_half=size_sum,
                         EN_all=c_all["E_N"], EN_kept=c_kept["E_N"] if c_kept else None,
                         precision_ok=bool(k and held.mean() < 0)))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tape", default=os.path.join(HERE, "..", "tester", "aos", "tape", "tape_P1obs.csv"))
    ap.add_argument("--json")
    ap.add_argument("--retain", type=float, default=RETAIN, help="target share of days kept (default 0.70)")
    a = ap.parse_args()
    globals()["RETAIN"] = a.retain
    df = load(a.tape)
    assets = sorted(df[df.role == "asset"].asset.unique())
    rng = np.random.default_rng(SEED)
    print(f"filled armed days: {len(df)} (assets {int((df.role == 'asset').sum())}, controls {int((df.role == 'control').sum())}),"
          f" months {df.month.min()} .. {df.month.max()}")
    allrows = []
    for name, make in models().items():
        oos = walk_forward(df, assets, name, make)
        print(f"\n== {name}: OOS months {oos.month.min()} .. {oos.month.max()}, rows {len(oos)}")
        print(f"  {'asset':15} {'n':>4} {'held':>4} {'ret':>5} {'E_all':>7} {'E_kept':>7} {'held_R':>7} {'held_BM':>8} "
              f"{'p_rand':>6} {'sumR':>7} {'kept':>7} {'0.5x':>7}  precision")
        for r in summarise(oos, name, rng):
            f = lambda x, d=3: "-" if x is None else f"{x:+.{d}f}"
            print(f"  {r['asset']:15} {r['n']:4} {r['withheld']:4} {r['retention']:5.0%} {f(r['E_all'])} {f(r['E_kept'])} "
                  f"{f(r['withheld_meanR'])} {f(r['withheld_BM'] and 100 * r['withheld_BM'], 1):>8} {r['p_vs_random']:6.2f} "
                  f"{r['sum_all']:+7.2f} {r['sum_kept']:+7.2f} {r['sum_size_half']:+7.2f}  {r['precision_ok']}")
            allrows.append(r)
        if name == "ridge":
            assets_only = df[df.role == "asset"]
            xtr, _ = design(assets_only, assets_only, assets)
            mu, sd = xtr.mean(), xtr.std().replace(0, 1.0)
            coef = pd.Series(Ridge(alpha=30.0).fit((xtr - mu) / sd, assets_only.y).coef_, index=xtr.columns)
            top = coef.reindex(coef.abs().sort_values(ascending=False).index)[:8]
            print("  full-sample ridge, largest standardised coefficients: "
                  + ", ".join(f"{k} {v:+.3f}" for k, v in top.items()))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(allrows, f, indent=1, default=float)


if __name__ == "__main__":
    main()
