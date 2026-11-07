"""INF-P1-T02 / T04: Postgres for the infra stack. psql and pg_dump run inside the db container, so the host needs no
Postgres driver. Credentials: infra/.env if present, else the local defaults.

infra/compose.yaml is the stack definition. This module runs the same pinned images with the plain docker CLI and
the names compose would give them (cycleorb-db-1, volume cycleorb_corb_pg, network cycleorb_default), because the
compose plugin hangs on this workstation's Docker Desktop. Image references are read from compose.yaml.
"""
import glob
import os
import re
import subprocess
import time

from corb import contract
from corb.paths import INFRA, VAR

COMPOSE_FILE = os.path.join(INFRA, "compose.yaml")
CONTAINER, VOLUME, NETWORK = "cycleorb-db-1", "cycleorb_corb_pg", "cycleorb_default"
MIGRATIONS = os.path.join(INFRA, "db", "migrations")
SNAPSHOT = os.path.join(INFRA, "db", "schema.sql")
SCRATCH = "corb_scratch"
CONTAINER_VAR = "/corb/var"


def _env():
    env = dict(CORB_DB_USER="corb", CORB_DB_PASSWORD="corb_local_only", CORB_DB_NAME="corb")
    path = os.path.join(INFRA, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            env.update(line.strip().split("=", 1) for line in f if "=" in line and not line.startswith("#"))
    env.update({k: v for k, v in os.environ.items() if k.startswith("CORB_DB_")})
    return env


ENV = _env()
USER, NAME = ENV["CORB_DB_USER"], ENV["CORB_DB_NAME"]


def _images():
    with open(COMPOSE_FILE, encoding="utf-8") as f:
        refs = re.findall(r"^\s*image:\s*(\S+)", f.read(), re.M)
    return dict(db=next(r for r in refs if r.startswith("postgres")), dbmate=next(r for r in refs if "dbmate" in r))


def _docker(args, stdin=None, check=True):
    p = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, encoding="utf-8")
    if check and p.returncode:
        raise RuntimeError(f"docker {' '.join(args[:3])} … failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout


def up(timeout=90):
    if _docker(["network", "ls", "-q", "-f", f"name=^{NETWORK}$"]).strip() == "":
        _docker(["network", "create", NETWORK])
    state = _docker(["ps", "-a", "-q", "-f", f"name=^{CONTAINER}$"]).strip()
    if not state:
        os.makedirs(VAR, exist_ok=True)
        _docker(["run", "-d", "--name", CONTAINER, "--network", NETWORK, "--network-alias", "db",
                 "-e", f"POSTGRES_USER={USER}", "-e", f"POSTGRES_PASSWORD={ENV['CORB_DB_PASSWORD']}",
                 "-e", f"POSTGRES_DB={NAME}", "-p", f"127.0.0.1:{ENV.get('CORB_DB_PORT', '5433')}:5432",
                 "-v", f"{VOLUME}:/var/lib/postgresql/data", "-v", f"{VAR}:{CONTAINER_VAR}:ro",
                 "--health-cmd", f"pg_isready -U {USER} -d {NAME}", "--health-interval", "2s",
                 _images()["db"]])
    else:
        _docker(["start", CONTAINER])
    end = time.time() + timeout
    while time.time() < end:
        if _docker(["inspect", "-f", "{{.State.Health.Status}}", CONTAINER]).strip() == "healthy":
            return
        time.sleep(1)
    raise RuntimeError(f"{CONTAINER} not healthy after {timeout} s")


def psql(sql, db=NAME):
    return _docker(["exec", "-i", CONTAINER, "psql", "-U", USER, "-d", db, "-v", "ON_ERROR_STOP=1", "-qAt",
                    "-F", "\t", "-f", "-"], stdin=sql).strip("\r\n")   # keep tabs: they delimit empty columns


def dbmate(*args, db=NAME):
    url = f"postgres://{USER}:{ENV['CORB_DB_PASSWORD']}@db:5432/{db}?sslmode=disable"
    return _docker(["run", "--rm", "--network", NETWORK, "-v", f"{os.path.join(INFRA, 'db')}:/db:ro",
                    "-e", f"DATABASE_URL={url}", "-e", "DBMATE_MIGRATIONS_DIR=/db/migrations",
                    "-e", "DBMATE_NO_DUMP_SCHEMA=true", "-e", "DBMATE_WAIT=true", _images()["dbmate"], *args])


def schema_dump(db=NAME):
    """pg_dump -s with the per-run random \\restrict token and version banners removed (stable across runs)."""
    raw = _docker(["exec", CONTAINER, "pg_dump", "-s", "--no-owner", "--no-privileges", "-U", USER, "-d", db])
    keep = [ln for ln in raw.splitlines() if not ln.startswith(("\\restrict", "\\unrestrict", "-- Dumped"))]
    return "\n".join(keep).strip() + "\n"


def migrate():
    return dbmate("up")


def migrate_check(write_snapshot=False):
    """up / down to empty / up on a scratch database; both 'up' schemas must match each other and the snapshot."""
    psql(f"DROP DATABASE IF EXISTS {SCRATCH};", db="postgres")
    psql(f"CREATE DATABASE {SCRATCH};", db="postgres")
    try:
        dbmate("up", db=SCRATCH)
        first = schema_dump(SCRATCH)
        for _ in glob.glob(os.path.join(MIGRATIONS, "*.sql")):
            dbmate("rollback", db=SCRATCH)
        left = psql("SELECT count(*) FROM pg_namespace WHERE nspname IN "
                    "('raw','core','features','train','score','ops');", db=SCRATCH)
        dbmate("up", db=SCRATCH)
        second = schema_dump(SCRATCH)
    finally:
        psql(f"DROP DATABASE IF EXISTS {SCRATCH};", db="postgres")
    if write_snapshot or not os.path.exists(SNAPSHOT):
        with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as f:
            f.write(first)
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = f.read()
    return dict(down_leaves_empty=left == "0", up_down_up_identical=first == second, matches_snapshot=first == snapshot)


def _col(name):
    return f'"{name}"' if name != name.lower() else name


def load():
    """Full reload in one transaction: TRUNCATE then \\copy every contract CSV and the landing register."""
    lines = ["BEGIN;", "TRUNCATE core.run, raw.source_file CASCADE;"]
    for name, r in contract.resources().items():
        cols = ", ".join(_col(f["name"]) for f in r["schema"]["fields"])
        lines.append(f"\\copy {r['x-table']} ({cols}) FROM '{CONTAINER_VAR}/contract/{name}.csv' "
                     f"WITH (FORMAT csv, HEADER true)")
    lines.append(f"\\copy raw.source_file FROM '{CONTAINER_VAR}/landing/source_file.csv' WITH (FORMAT csv, HEADER true)")
    lines.append("COMMIT;")
    psql("\n".join(lines) + "\n")


def load_incremental(run_keys):
    """INF-P2-T01: replace only the given runs (delete cascades, then copy var/stage/*.csv), upsert their ingest
    state, and add new landed files. One transaction. Returns the number of new raw.source_file rows."""
    lines = ["BEGIN;"]
    if run_keys:
        keys = ", ".join(f"'{k}'" for k in run_keys)
        lines.append(f"DELETE FROM core.run WHERE run_key IN ({keys});")
        for name, r in contract.resources().items():
            cols = ", ".join(_col(f["name"]) for f in r["schema"]["fields"])
            lines.append(f"\\copy {r['x-table']} ({cols}) FROM '{CONTAINER_VAR}/stage/{name}.csv' "
                         f"WITH (FORMAT csv, HEADER true)")
        lines += ["CREATE TEMP TABLE st (run_key text, content_sha256 text);",
                  f"\\copy st FROM '{CONTAINER_VAR}/stage/ingest_state.csv' WITH (FORMAT csv, HEADER true)",
                  "INSERT INTO ops.ingest_state SELECT run_key, content_sha256, now() FROM st ON CONFLICT (run_key) "
                  "DO UPDATE SET content_sha256 = EXCLUDED.content_sha256, ingested_at = EXCLUDED.ingested_at;"]
    lines += ["CREATE TEMP TABLE sf (LIKE raw.source_file);",
              f"\\copy sf FROM '{CONTAINER_VAR}/landing/source_file.csv' WITH (FORMAT csv, HEADER true)",
              "WITH ins AS (INSERT INTO raw.source_file SELECT * FROM sf ON CONFLICT (file_sha256) DO NOTHING "
              "RETURNING 1) SELECT count(*) FROM ins;",
              "COMMIT;"]
    return int(psql("\n".join(lines) + "\n").splitlines()[-1])


def columns_match_contract():
    """Live table columns (name, type, NOT NULL) vs the contract: [] when they agree."""
    rows = psql("SELECT table_schema || '.' || table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_schema IN ('core', 'features');")
    live = {}
    for ln in rows.splitlines():
        t, c, typ, nullable = ln.split("\t")
        live.setdefault(t, {})[c] = (typ, nullable == "NO")
    want_type = {"string": "text", "integer": "bigint", "number": "double precision", "boolean": "boolean",
                 "datetime": "timestamp with time zone", "date": "date"}
    diffs = []
    for r in contract.resources().values():
        cols = live.get(r["x-table"], {})
        for f in r["schema"]["fields"]:
            want = (want_type[f["type"]], bool(f.get("constraints", {}).get("required")))
            if cols.get(f["name"]) != want:
                diffs.append(f"{r['x-table']}.{f['name']}: db {cols.get(f['name'])} vs contract {want}")
        diffs += [f"{r['x-table']}.{c}: not in contract" for c in set(cols) - {f["name"] for f in r["schema"]["fields"]}]
    return diffs


def table_counts():
    res = contract.resources()
    q = " UNION ALL ".join(f"SELECT '{n}', count(*) FROM {r['x-table']}" for n, r in res.items())
    return {k: int(v) for k, v in (ln.split("\t") for ln in psql(q + ";").splitlines())}


def csv_counts():
    out = {}
    for name in contract.resources():
        with open(os.path.join(VAR, "contract", name + ".csv"), encoding="utf-8") as f:
            out[name] = sum(1 for _ in f) - 1
    return out


def fingerprint():
    return psql("""SELECT md5(string_agg(run_key || ':' || event_id || ':' || "pnl_R"::text, ','
                    ORDER BY run_key, event_id)) FROM core.event;""")


def health(run_id):
    row = psql(f"SELECT n, wr, r_payoff, bwr, bm, e FROM core.v_health WHERE run_id = '{run_id}';")
    if not row:
        return None
    n, wr, r, bwr, bm, e = row.split("\t")
    return dict(n=int(n), WR=float(wr), R=float(r), BWR=float(bwr), BM=float(bm), E=float(e))


def funnel(run_id, counter):
    v = psql(f"SELECT f.value FROM core.funnel f JOIN core.run r USING (run_key) "
             f"WHERE r.run_id = '{run_id}' AND f.counter = '{counter}';")
    return int(v) if v else 0


def event_vector(run_id):
    return psql(f"""SELECT string_agg(event_id || '=' || "pnl_R"::text, ',' ORDER BY event_id)
                    FROM core.event JOIN core.run USING (run_key) WHERE run_id = '{run_id}';""")


# edge_framework.md Appendix B, same tolerances as tests/test_framework.py
COFX_HEALTH = [
    ("CO-FX-01", "vle1.08_EURUSD_26110200_2026-01-01_2026-10-31_500",
     dict(n=(95, 0), WR=(0.484, 0.005), R=(1.63, 0.005), BWR=(0.380, 0.005), BM=(0.104, 0.001), E=(0.254, 0.005))),
    ("CO-FX-02", "v1.09_SPX500_26110900_2025-07-01_2026-10-31_1000",
     dict(n=(71, 0), WR=(0.563, 0.005), R=(1.51, 0.005), BM=(0.165, 0.001))),
    ("CO-FX-03", "v1.09_UK100_26110800_2025-12-17_2026-10-31_500", dict(n=(54, 0))),
    ("CO-FX-03", "v1.09_UK100_26110800_2025-12-17_2026-10-31_1000", dict(n=(88, 0))),
    ("CO-FX-04", "v1.09_DE30_26110310_2025-07-01_2026-10-31_1000", dict(n=(120, 0), E=(0.235, 0.005))),
]
COFX_FUNNEL = [
    ("CO-FX-02", "v1.09_SPX500_26110900_2025-07-01_2026-10-31_1000", "close_fail", 0),
    ("CO-FX-02", "v1.09_SPX500_26110900_2025-07-01_2026-10-31_1000", "skip_skip_date", 6),
    ("CO-FX-03", "v1.09_UK100_26110800_2025-12-17_2026-10-31_500", "sides_lot_min", 82),
    ("CO-FX-03", "v1.09_UK100_26110800_2025-12-17_2026-10-31_1000", "sides_lot_min", 0),
]


def check(reload=False):
    from corb.baseline import check as chk
    from corb.paths import RUNS
    contract.build_all(RUNS, os.path.join(VAR, "contract"), live_root=os.path.join(VAR, "live"))  # fresh reference
    out = []
    n, bad, worst = psql("SELECT count(*), count(*) FILTER (WHERE abs(pnl_r_rebuilt - pnl_r_contract) > 1e-6), "
                         "coalesce(max(abs(pnl_r_rebuilt - pnl_r_contract)), 0) FROM core.v_event_r;").split("\t")
    out.append(chk("rebuild.events_with_pnl_R_diff_gt_1e-6", 0, int(bad), 0))
    out.append(chk("rebuild.max_abs_diff_R", 0.0, float(worst), 1e-6))
    out.append(chk("schema.columns_match_contract", 0, len(columns_match_contract()), 0))
    db_n, csv_n = table_counts(), csv_counts()
    out += [chk(f"rows.{k}", csv_n[k], db_n[k], 0) for k in csv_n]
    out.append(chk("rebuild.events_covered", db_n["event"], int(n), 0))
    for fx, run_id, want in COFX_HEALTH:
        got = health(run_id) or {}
        out += [chk(f"{fx}.{run_id[:20]}.{k}", v, got.get(k), tol) for k, (v, tol) in want.items()]
    for fx, run_id, counter, want in COFX_FUNNEL:
        out.append(chk(f"{fx}.{run_id[:20]}.{counter}", want, funnel(run_id, counter), 0))
    out.append(chk("CO-FX-04.de40_500_vs_1000_identical_events",
                   event_vector("v1.09_DE30_26110310_2025-07-01_2026-10-31_500"),
                   event_vector("v1.09_DE30_26110310_2025-07-01_2026-10-31_1000"), 0))
    unlanded = psql("SELECT count(*) FROM core.run r WHERE NOT EXISTS "
                    "(SELECT 1 FROM raw.source_file s WHERE s.file_sha256 = r.events_sha256);")
    out.append(chk("landing.runs_without_landed_events_file", 0, int(unlanded), 0))
    fp = fingerprint()
    if reload:
        load()
        out.append(chk("reload.fingerprint_identical", fp, fingerprint(), 0))
    return out, fp
