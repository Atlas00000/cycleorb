"""Unified Edge Framework metrics with the CycleORB overrides (doc/edge_framework.md).

Pure functions on lists of per-event pnl_R. Standard library only.
"""
import math
import random
import statistics as st

Z95 = 1.96


# ---------------------------------------------------------------- Stage 0 / 1
def bwr(r):
    """Breakeven win rate for realised payoff R (generic §3.2)."""
    return 1.0 / (1.0 + r)


def e_n(wr, r):
    """Normalised expectancy in AL units (generic §3.1)."""
    return wr * (r + 1.0) - 1.0


def leak(c_r, r):
    """WR-equivalent leak of a per-event cost in R (generic §4.3)."""
    return c_r / (r + 1.0)


def wilson_interval(p, n, z=Z95):
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def wilson_half(p, n, z=Z95):
    lo, hi = wilson_interval(p, n, z)
    return (hi - lo) / 2.0


def uncertainty_margin(p, n, z=Z95):
    """Generic §4.4: normal half-width, Wilson when n < 200. CycleORB scoring uses wilson_half throughout (n < 200)."""
    return wilson_half(p, n, z) if n < 200 else z * math.sqrt(p * (1 - p) / n)


def sample_size(eps, p=0.5, z=Z95):
    """Generic §5.2 / FX-08 evidence tier size (informational only for CycleORB, CO-01)."""
    return math.ceil(z * z * p * (1 - p) / (eps * eps))


def fmi(wr, b):
    return (wr - b) / b


def core(rs):
    """Health-vector core over trade events. Zero-R events are excluded from WR / payoff (generic §1.3 rule 5)."""
    n = len(rs)
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    out = dict(n=n, wins=len(wins), losses=len(losses), E=sum(rs) / n if n else 0.0,
               sd=st.pstdev(rs) if n > 1 else 0.0)
    if not wins or not losses:
        out.update(WR=len(wins) / max(1, len(wins) + len(losses)), AW=None, AL=None, R=None, BWR=None, BM=None,
                   FMI=None, E_N=None, PF=None)
        return out
    wr = len(wins) / (len(wins) + len(losses))
    aw, al = sum(wins) / len(wins), sum(losses) / len(losses)
    r = aw / al
    b = bwr(r)
    out.update(WR=wr, AW=aw, AL=al, R=r, BWR=b, BM=wr - b, FMI=(wr - b) / b, E_N=e_n(wr, r),
               PF=sum(wins) / sum(losses))
    return out


def binom_sf(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def bootstrap_r(rs, iters=10000, seed=1):
    rng = random.Random(seed)
    n = len(rs)
    vals = []
    for _ in range(iters):
        s = [rs[rng.randrange(n)] for _ in range(n)]
        w = [x for x in s if x > 0]
        l = [-x for x in s if x < 0]
        if w and l:
            vals.append((sum(w) / len(w)) / (sum(l) / len(l)))
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def expected_streak(n, wr):
    """Expected worst losing streak in n trials (generic §5.2)."""
    return math.log(n) / math.log(1.0 / (1.0 - wr))


def max_loss_streak(rs):
    best = cur = 0
    for x in rs:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def loss_skew(rs):
    losses = [x for x in rs if x < 0]
    if len(losses) < 3:
        return 0.0
    m, s = st.mean(losses), st.pstdev(losses)
    return (sum((x - m) ** 3 for x in losses) / len(losses)) / s ** 3 if s > 0 else 0.0


def aggregate_legs(legs_ccy, costs_ccy, risk_ccy):
    """One trade event from several legs (generic §1.3 / FX-14): pnl_R = (sum legs - costs) / declared 1R."""
    return (sum(legs_ccy) - costs_ccy) / risk_ccy


# ---------------------------------------------------------------- Stage 3
def kelly_binary(p, b):
    return (b * p - (1 - p)) / b


def kelly_continuous(rs):
    v = st.pvariance(rs)
    return st.mean(rs) / v if v > 0 else 0.0


def geometric_g(returns):
    c = 1.0
    for r in returns:
        c *= 1 + r
    return c ** (1.0 / len(returns)) - 1.0


def vol_drag(mu, sigma):
    return mu - sigma * sigma / 2.0


def recovery_return(dd):
    return dd / (1.0 - dd)


def max_drawdown(returns, start=1.0):
    eq = pk = start
    dd = 0.0
    for r in returns:
        eq *= 1 + r
        pk = max(pk, eq)
        dd = max(dd, 1 - eq / pk)
    return dd


def max_drawdown_r(rs):
    """Closed-event drawdown in R units (sizing-independent)."""
    cum = pk = dd = 0.0
    for x in rs:
        cum += x
        pk = max(pk, cum)
        dd = max(dd, pk - cum)
    return dd


def _path(seq, f):
    eq = pk = 1.0
    dd = 0.0
    ruin = False
    for x in seq:
        eq *= 1 + f * x
        pk = max(pk, eq)
        dd = max(dd, 1 - eq / pk)
        ruin = ruin or eq <= 0.5
    return eq, dd, ruin


def monte_carlo(rs, f, mode="block", block=10, iters=5000, stress=None, seed=1):
    """MC-1 (mode='shuffle') / MC-2 (block bootstrap, CO-11 block 10) / MC-3 (pass stress=)."""
    rng = random.Random(seed)
    n = len(rs)
    blocks = [rs[i:i + block] for i in range(0, max(1, n - block + 1))]
    terms, dds, ruins = [], [], 0
    for _ in range(iters):
        if mode == "shuffle":
            seq = rs[:]
            rng.shuffle(seq)
        else:
            seq = []
            while len(seq) < n:
                seq += blocks[rng.randrange(len(blocks))]
            seq = seq[:n]
        if stress:
            seq = stress(seq, rng)
        eq, dd, ru = _path(seq, f)
        terms.append(eq)
        dds.append(dd)
        ruins += ru
    terms.sort()
    dds.sort()
    return dict(p95dd=dds[int(0.95 * iters)], p50dd=dds[iters // 2], med_term=terms[iters // 2],
                p5_term=terms[int(0.05 * iters)], ruin=ruins / iters)


def mc3_stress(wr, m, al, c_total):
    """MC-3: wins become -AL with prob M/WR, wins x0.9, costs +50 %."""
    p = m / wr

    def stress(seq, rng):
        out = []
        for x in seq:
            if x > 0 and rng.random() < p:
                x = -al
            elif x > 0:
                x *= 0.9
            out.append(x - 0.5 * c_total)
        return out
    return stress


def f_at_dd(rs, dd_limit=0.25, iters=1500, seed=1):
    """Largest f with MC-2 P95 MaxDD <= dd_limit (bisection)."""
    lo, hi = 0.001, 0.15
    for _ in range(14):
        mid = (lo + hi) / 2
        if monte_carlo(rs, mid, iters=iters, seed=seed)["p95dd"] <= dd_limit:
            lo = mid
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------- Stage 2 (CycleORB overrides)
def lifecycle(rs, e_base, leak_pp):
    """edge_framework.md §6.1: W20 / W40 / W80, decision on W40, confirm on W80."""
    def ef(seg):
        c = core(seg)
        return None if c["BM"] is None else c["BM"] - leak_pp, c["E"]

    win = {}
    for w in (20, 40, 80):
        if len(rs) >= w:
            efw, ew = ef(rs[-w:])
            win[w] = dict(EF=efw, E=ew)
    d_d = None
    if len(rs) >= 80 and win[40]["EF"] is not None:
        prev = ef(rs[-80:-40])[0]
        d_d = None if prev is None else win[40]["EF"] - prev
    w40, w80 = win.get(40), win.get(80)
    if not w40 or w40["EF"] is None:
        state = "n/a"
    elif w40["EF"] <= 0 and (not w80 or w80["EF"] is None or w80["EF"] <= 0):
        state = "Below frontier"
    elif w40["EF"] <= 0:
        state = "Near frontier"
    elif w40["E"] <= e_base - 0.10 or (d_d is not None and d_d <= -0.05):
        state = "Compressing"
    elif w40["E"] >= e_base + 0.10:
        state = "Expanding"
    else:
        state = "Stable"
    return dict(windows=win, dD=d_d, state=state)


def folds(rs, k=4):
    size = len(rs) // k
    parts = [rs[i * size:(i + 1) * size] for i in range(k - 1)] + [rs[(k - 1) * size:]]
    return [sum(p) / len(p) for p in parts]
