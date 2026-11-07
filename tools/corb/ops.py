"""INF-P5: observability and operations.

log()            structured JSON lines per job: var/log/<job>/<date>.jsonl (T01)
load_journals()  every landed tester journal -> raw.journal_line with run segment, sim time and event_id (T01)
reason_codes()   the catalogue of shadow / guard reason codes -> ops.reason_code (T03)
collect()        operational metrics -> ops.metric with ok / warn / alarm (T02)
roles()          database roles ingest_rw / train_rw / agent_ro + permission checks (T06)
secret_scan()    no credential from infra/.env appears anywhere in git history (T06)
enqueue() / work()  Postgres job queue, FOR UPDATE SKIP LOCKED (T05)
"""
import csv
import glob
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

from corb import db
from corb.paths import INFRA, REPO, TOOLS, VAR, git_info
from corb.textio import read_text

LOG_DIR = os.path.join(VAR, "log")
STAGE = os.path.join(VAR, "stage")


# ---------------------------------------------------------------- T01 logs
def log(job, level="info", msg="", **fields):
    os.makedirs(os.path.join(LOG_DIR, job), exist_ok=True)
    rec = dict(ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"), level=level, job=job, msg=msg,
               git=(git_info().get("head") or "")[:12], **fields)
    with open(os.path.join(LOG_DIR, job, datetime.now().strftime("%Y-%m-%d") + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


RE_START = re.compile(r"\t(\S+),M\d+: testing of .* started with inputs")
RE_MAGIC = re.compile(r"\t  InpMagicBase=(\d+)")
RE_VERSION = re.compile(r"\[CycleORB\] Init OK v([\d\.]+)")
RE_EVENT = re.compile(r"\t(\d{4}\.\d\d\.\d\d \d\d:\d\d:\d\d)\s+(.*)$")
RE_DAY = re.compile(r"\[CycleORB\] (RANGE|SKIP|PLACE|HEALTH|GUARD|CLOSE|CYCLE_\w+)\s*(LON|NY|TKY)?\s*(\d{4}\.\d\d\.\d\d)?")
OFFSET = {"LON": 1, "NY": 2, "TKY": 3}


def parse_journal(path):
    """Yield (line_no, run_seq, symbol, version, sim_time, event_id, kind, message) for one tester journal."""
    seq, symbol, version, magic = -1, None, None, None
    for n, line in enumerate(read_text(path).splitlines(), start=1):
        m = RE_START.search(line)
        if m:
            seq, symbol, version, magic = seq + 1, m.group(1), None, None
        mm = RE_MAGIC.search(line)
        if mm:
            magic = int(mm.group(1))
        v = RE_VERSION.search(line)
        if v:
            version = v.group(1)
        ev = RE_EVENT.search(line)
        sim, msg = (ev.group(1).replace(".", "-"), ev.group(2)) if ev else (None, line.split("\t")[-1])
        kind = event_id = None
        d = RE_DAY.search(msg)
        if d:
            kind = d.group(1)
            if d.group(2) and d.group(3) and magic:
                event_id = f"{magic + OFFSET[d.group(2)]}-{d.group(3).replace('.', '')}"
        yield n, seq if seq >= 0 else None, symbol, version, sim, event_id, kind, msg[:2000]


def load_journals():
    have = {r for r in db.psql("SELECT DISTINCT file_sha256 FROM raw.journal_line;").splitlines() if r}
    files = [ln.split("\t") for ln in db.psql("SELECT file_sha256, landed_path FROM raw.source_file "
                                              "WHERE kind = 'journal';").splitlines() if ln]
    loaded = 0
    os.makedirs(STAGE, exist_ok=True)
    for sha, rel in files:
        if sha in have:
            continue
        path = os.path.join(VAR, "landing", rel)
        out = os.path.join(STAGE, "journal_line.csv")
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["file_sha256", "line_no", "run_seq", "symbol", "ea_version", "sim_time", "event_id", "kind",
                        "message"])
            for row in parse_journal(path):
                w.writerow([sha, *["" if x is None else x for x in row]])
        db.psql("\\copy raw.journal_line (file_sha256, line_no, run_seq, symbol, ea_version, sim_time, event_id, kind, "
                "message) FROM '/corb/var/stage/journal_line.csv' WITH (FORMAT csv, HEADER true)\n")
        loaded += 1
    total = int(db.psql("SELECT count(*) FROM raw.journal_line;"))
    return dict(journals_loaded=loaded, journals_total=len(files), lines=total)


def why(event_id):
    """Every journal line that names this setup-day, in time order."""
    return [ln.split("\t") for ln in db.psql(
        f"SELECT sim_time, symbol, ea_version, kind, message FROM raw.journal_line WHERE event_id = '{event_id}' "
        f"ORDER BY sim_time, line_no;").splitlines() if ln]


# ---------------------------------------------------------------- T03 reason codes
REASON_CODES = [
    ("ALLOW_DEFAULT", "L2 shadow", "fire", "Default: no rule asked to skip"),
    ("ALLOW_UNSURE", "L2 shadow", "fire", "Model predicted E in (-0.10, 0]: not sure enough to skip, fired and logged"),
    ("ALLOW_BUDGET_CAP", "L2 shadow", "fire", "A skip beyond the 15 % per-asset budget, released (least severe first)"),
    ("ALLOW_GUARD_DECAY", "L2 shadow", "fire", "Training window failed the decay guard: no model applied, fired"),
    ("SKIP_CELL_BM_NEG", "L2 shadow", "skip", "Decision-time cell with BM <= 0 on actual and shadow (n >= 15, training folds)"),
    ("SKIP_MODEL_LOSER", "L2 shadow", "skip", "Model: predicted E <= -0.10R and P(R < 0) >= 0.60"),
    ("GUARD_CALENDAR_KILL", "L3 guard", "block", "Refused close / carried position: no new entries until cleared"),
    ("GUARD_SLIP_ABORT", "L3 guard", "block", "Entry filled > 0.25R beyond the planned entry: closed at market"),
    ("GUARD_LOT_MIN", "L3 guard", "block", "> 10 % of the last 40 armed sides below the minimum lot: asset stopped"),
    ("GUARD_DD_HALVE", "L3 guard", "block", "Own-equity drawdown >= 0.8 x the asset limit: size halved"),
]


def reason_codes():
    db.psql("BEGIN;\nDELETE FROM ops.reason_code;\n" + "\n".join(
        f"INSERT INTO ops.reason_code VALUES ('{c}', '{l}', '{v}', '{m.replace(chr(39), chr(39) * 2)}');"
        for c, l, v, m in REASON_CODES) + "\nCOMMIT;\n")
    used = {r for r in db.psql("SELECT DISTINCT reason_code FROM score.shadow_decision;").splitlines() if r}
    return dict(codes=len(REASON_CODES), used_in_shadow=sorted(used),
                uncatalogued=sorted(used - {c[0] for c in REASON_CODES}))


# ---------------------------------------------------------------- T02 metrics
def _skip_dates(preset):
    from corb.ingest import parse_set
    raw = parse_set(preset).get("InpSkipDates", "")
    out = []
    for tok in [t.strip() for t in raw.split(",") if t.strip()]:
        s = tok if len(tok) == 8 else "20" + tok
        out.append(date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    return out


def collect(today=None):
    today = today or date.today()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []

    def add(name, subject, value, status, detail=""):
        rows.append(dict(ts=now, name=name, subject=subject, value=value, status=status, detail=detail))

    with open(os.path.join(INFRA, "baseline_lock.json"), encoding="utf-8") as f:
        lock = json.load(f)
    for asset, b in lock["primary"].items():
        q = db.psql(f"""SELECT count(*) FILTER (WHERE e.local_day > (SELECT max(local_day) FROM core.event x
                           WHERE x.run_key = r.run_key) - 90), avg(e."c_spread_R") FILTER (WHERE e.local_day >
                           (SELECT max(local_day) FROM core.event x WHERE x.run_key = r.run_key) - 90)
                        FROM core.event e JOIN core.run r USING (run_key) WHERE r.run_id = '{b['run_id']}';""")
        n90, spread = q.split("\t")
        ratio = int(n90) / b["fires_90d"] if b["fires_90d"] else None
        add("fires_90d_vs_baseline", asset, ratio, "ok" if ratio is None or ratio >= 0.7 else
            ("warn" if ratio >= 0.5 else "alarm"), f"{n90} fires in the last 90 days; FREQUENCY_STALL below 50 %")
    for asset, fam_rows in _shadow_rates().items():
        for fam, rate in fam_rows.items():
            add(f"shadow_skip_rate_{fam}", asset, rate, "ok" if rate <= 0.15 else "warn", "low-bar budget 15 %")
    for asset, share in _feature_nulls().items():
        add("feature_null_share", asset, share, "ok" if share <= 0.05 else "warn",
            "share of evaluated days with a missing EA feature value")
    for asset, drift in _cost_drift().items():
        add("cost_drift_w40", asset, drift, "ok" if drift is None or drift <= 1.5 else "alarm",
            "c_spread_R W40 / full-sample (edge_framework.md §6.2: alarm above 1.5x)")
    lag = db.psql("SELECT extract(epoch FROM now() - max(landed_at)) / 3600 FROM raw.source_file;")
    add("ingest_lag_hours", "*", float(lag) if lag else None, "ok", "hours since the last landed file")
    fails = int(db.psql("SELECT count(*) FROM ops.dq_result WHERE status = 'fail';"))
    add("dq_failures", "*", fails, "ok" if fails == 0 else "alarm")
    for preset in sorted(glob.glob(os.path.join(REPO, "Presets", "AOS", "AOS-P3-REC_*.set"))):
        dates = _skip_dates(preset)
        name = os.path.basename(preset)[11:-4]
        if not dates:
            add("skip_dates_horizon_days", name, None, "ok", "empty list by design (market trades its holidays)")
            continue
        days = (max(dates) - today).days
        add("skip_dates_horizon_days", name, days, "ok" if days >= 180 else ("warn" if days >= 90 else "alarm"),
            f"last skip date {max(dates)}; extend every December")
    cal = db.psql("SELECT max(last_event) FROM features.calendar_snapshot;")
    if cal:
        days = (datetime.fromisoformat(cal.replace(" ", "T")).date() - today).days
        add("calendar_horizon_days", "*", days, "ok" if days >= 180 else ("warn" if days >= 90 else "alarm"),
            "last high-impact event in the calendar snapshot")
    path = os.path.join(STAGE, "metric.csv")
    os.makedirs(STAGE, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "name", "subject", "value", "status", "detail"])
        w.writeheader()
        w.writerows({**r, "value": "" if r["value"] is None else r["value"]} for r in rows)
    db.psql("\\copy ops.metric (ts, name, subject, value, status, detail) FROM '/corb/var/stage/metric.csv' "
            "WITH (FORMAT csv, HEADER true)\n")
    return rows


def _shadow_rates():
    out = {}
    for ln in db.psql("""SELECT s.asset, split_part(m.family, '_', 1), avg((s.verdict = 'skip')::int)
                         FROM score.shadow_decision s JOIN score.eval_run e USING (eval_id)
                         JOIN train.model_version m USING (model_semver)
                         WHERE e.created_at = (SELECT max(created_at) FROM score.eval_run e2 WHERE e2.recipe = e.recipe)
                         GROUP BY 1, 2;""").splitlines():
        a, fam, rate = ln.split("\t")
        out.setdefault(a, {})[fam] = float(rate)
    return out


def _feature_nulls():
    out = {}
    for ln in db.psql("""SELECT t.asset, avg((t.vol_pct IS NULL OR t.trend_side IS NULL)::int)
                         FROM features.regime_tape t WHERE t.decision = 'ARMED' GROUP BY 1;""").splitlines():
        a, v = ln.split("\t")
        out[a] = float(v)
    return out


def _cost_drift():
    out = {}
    with open(os.path.join(INFRA, "baseline_lock.json"), encoding="utf-8") as f:
        lock = json.load(f)
    for asset, b in lock["primary"].items():
        q = db.psql(f"""WITH e AS (SELECT "c_spread_R" c, row_number() OVER (ORDER BY local_day DESC) rn
                                    FROM core.event JOIN core.run USING (run_key) WHERE run_id = '{b['run_id']}')
                        SELECT avg(c) FILTER (WHERE rn <= 40) / nullif(avg(c), 0) FROM e;""")
        out[asset] = float(q) if q else None
    return out


# ---------------------------------------------------------------- T06 roles and secrets
ROLES = {
    "ingest_rw": dict(write=["raw", "core", "features", "ops"], read=["train", "score"]),
    "train_rw": dict(write=["train", "score", "ops"], read=["raw", "core", "features"]),
    "agent_ro": dict(write=[], read=["raw", "core", "features", "train", "score", "ops"]),
}


def _env_path():
    return os.path.join(INFRA, ".env")


def _ensure_passwords():
    """Role passwords live in infra/.env (gitignored); generate any that are missing."""
    path = _env_path()
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    env = dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))
    added = []
    for role in ROLES:
        key = f"CORB_DB_{role.upper()}_PASSWORD"
        if not env.get(key):
            env[key] = secrets.token_urlsafe(18)
            added.append(f"{key}={env[key]}")
    if added:
        with open(path, "a", encoding="utf-8") as f:
            f.write(("\n" if text and not text.endswith("\n") else "") + "# INF-P5-T06 database roles\n"
                    + "\n".join(added) + "\n")
    return {r: env[f"CORB_DB_{r.upper()}_PASSWORD"] for r in ROLES}


def roles():
    pw = _ensure_passwords()
    sql = ["BEGIN;"]
    for role, spec in ROLES.items():
        p = pw[role].replace("'", "''")
        sql.append(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                   f"CREATE ROLE {role} LOGIN; END IF; END $$;")
        sql.append(f"ALTER ROLE {role} WITH LOGIN PASSWORD '{p}';")
        sql.append(f"GRANT CONNECT ON DATABASE {db.NAME} TO {role};")
        for s in spec["read"] + spec["write"]:
            sql += [f"GRANT USAGE ON SCHEMA {s} TO {role};", f"GRANT SELECT ON ALL TABLES IN SCHEMA {s} TO {role};",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT SELECT ON TABLES TO {role};"]
        for s in spec["write"]:
            sql += [f"GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {s} TO {role};",
                    f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA {s} TO {role};",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {s} GRANT INSERT, UPDATE, DELETE ON TABLES TO {role};"]
    sql.append("COMMIT;")
    db.psql("\n".join(sql) + "\n")
    return permission_checks(pw)


def _as(role, password, sql):
    p = subprocess.run(["docker", "exec", "-i", "-e", f"PGPASSWORD={password}", db.CONTAINER, "psql", "-h", "localhost",
                        "-U", role, "-d", db.NAME, "-v", "ON_ERROR_STOP=1", "-qAt", "-c", sql],
                       capture_output=True, text=True)
    return p.returncode == 0


def permission_checks(pw):
    checks = []
    expect = [("agent_ro", "SELECT count(*) FROM core.run", True), ("agent_ro", "SELECT count(*) FROM score.eval_run", True),
              ("agent_ro", "DELETE FROM core.funnel WHERE false", False),
              ("agent_ro", "INSERT INTO ops.metric VALUES (now(), 'x', 'x', 0, 'ok', '')", False),
              ("ingest_rw", "DELETE FROM core.funnel WHERE false", True),
              ("ingest_rw", "DELETE FROM train.dataset WHERE false", False),
              ("train_rw", "DELETE FROM score.shadow_decision WHERE false", True),
              ("train_rw", "DELETE FROM core.run WHERE false", False)]
    for role, sql, allowed in expect:
        ok = _as(role, pw[role], sql)
        checks.append(dict(name=f"{role}: {sql.split(' FROM ')[0].split(' INTO ')[0]} "
                                f"{sql.split(' FROM ')[-1].split(' ')[0] if ' FROM ' in sql else 'ops.metric'}",
                           expected=allowed, got=ok, ok=ok == allowed))
    return checks


def secret_scan():
    """Every password in infra/.env must be absent from all git history (account numbers are identifiers, not
    credentials). A password equal to the committed .env.example placeholder counts as exposed."""
    path = _env_path()
    if not os.path.exists(path):
        return dict(values_checked=0, found=[])
    env = dict(line.strip().split("=", 1) for line in open(path, encoding="utf-8")
               if "=" in line and not line.startswith("#"))
    values = {k: v for k, v in env.items() if v and "PASSWORD" in k and len(v) >= 5}
    log_text = subprocess.run(["git", "log", "-p", "--all"], cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout
    found = [k for k, v in values.items() if v in log_text]
    tracked = subprocess.run(["git", "ls-files", "infra/.env"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return dict(values_checked=len(values), found_in_history=found, env_tracked=bool(tracked))


# ---------------------------------------------------------------- T02 Grafana
GRAFANA_NAME = "cycleorb-grafana"
GRAFANA_URL = "http://127.0.0.1:3000"


def _grafana_api(path, password, body=None):
    import base64
    import urllib.request
    req = urllib.request.Request(GRAFANA_URL + path, data=None if body is None else json.dumps(body).encode(), headers={
        "Content-Type": "application/json",
        "Authorization": "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def grafana_up():
    """Start Grafana on the compose network (localhost only, read-only DB role), then verify through its API:
    datasource reaches Postgres and the provisioned dashboard's panels all return data without error."""
    pw = _ensure_passwords()
    path = _env_path()
    env = dict(line.strip().split("=", 1) for line in open(path, encoding="utf-8") if "=" in line and not line.startswith("#"))
    admin = env.get("CORB_GRAFANA_ADMIN_PASSWORD")
    if not admin:
        admin = secrets.token_urlsafe(18)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"# INF-P5-T02 Grafana admin\nCORB_GRAFANA_ADMIN_PASSWORD={admin}\n")
    subprocess.run(["docker", "rm", "-f", GRAFANA_NAME], capture_output=True)
    prov = os.path.join(INFRA, "grafana", "provisioning")
    p = subprocess.run(["docker", "run", "-d", "--name", GRAFANA_NAME, "--network", db.NETWORK, "--restart", "unless-stopped",
                        "-p", "127.0.0.1:3000:3000", "-v", f"{prov}:/etc/grafana/provisioning:ro",
                        "-v", "cycleorb_grafana:/var/lib/grafana",
                        "-e", f"GF_SECURITY_ADMIN_PASSWORD={admin}", "-e", f"CORB_DB_AGENT_RO_PASSWORD={pw['agent_ro']}",
                        "-e", "GF_ANALYTICS_REPORTING_ENABLED=false", "-e", "GF_ANALYTICS_CHECK_FOR_UPDATES=false",
                        db._images()["grafana"]], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    for _ in range(60):
        try:
            _grafana_api("/api/health", admin)
            break
        except OSError:
            time.sleep(2)
    # an existing grafana volume keeps the first admin password; reset it to the one in .env
    subprocess.run(["docker", "exec", GRAFANA_NAME, "grafana", "cli", "admin", "reset-admin-password", admin],
                   capture_output=True)
    ds = _grafana_api("/api/datasources/uid/cycleorb/health", admin)
    dash = _grafana_api("/api/dashboards/uid/cycleorb-ops", admin)["dashboard"]
    panels = []
    for panel in dash["panels"]:
        body = {"queries": [dict(t, datasource=panel["datasource"]) for t in panel["targets"]], "from": "now-30d", "to": "now"}
        try:
            res = _grafana_api("/api/ds/query", admin, body)["results"]["A"]
            values = res["frames"][0]["data"]["values"] if res.get("frames") else []
            panels.append(dict(title=panel["title"], rows=len(values[0]) if values else 0, error=res.get("error")))
        except OSError as e:
            panels.append(dict(title=panel["title"], rows=0, error=(e.read().decode() if hasattr(e, "read") else str(e))[:200]))
    return dict(url=GRAFANA_URL, datasource=ds.get("status"), datasource_message=ds.get("message"), panels=panels)


def grafana_down():
    subprocess.run(["docker", "rm", "-f", GRAFANA_NAME], capture_output=True)


# ---------------------------------------------------------------- T05 job queue
def enqueue(command):
    c = command.replace("'", "''")
    return int(db.psql(f"INSERT INTO ops.job (command) VALUES ('{c}') RETURNING job_id;").splitlines()[0])


def work(once=False, poll=10):
    """Claim the oldest queued job (SKIP LOCKED, so several workers can share the queue), run `python -m corb
    <command>`, store status, exit code and log path. Returns the jobs processed."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    done = []
    while True:
        row = db.psql(f"""UPDATE ops.job SET status = 'running', started_at = now(), worker = '{worker}'
                          WHERE job_id = (SELECT job_id FROM ops.job WHERE status = 'queued' ORDER BY job_id
                                          FOR UPDATE SKIP LOCKED LIMIT 1)
                          RETURNING job_id, command;""").splitlines()
        if not row:
            if once:
                return done
            time.sleep(poll)
            continue
        job_id, command = row[0].split("\t", 1)
        os.makedirs(os.path.join(LOG_DIR, "jobs"), exist_ok=True)
        log_path = os.path.join(LOG_DIR, "jobs", f"{job_id}.log")
        log("jobs", msg="start", job_id=int(job_id), command=command, worker=worker)
        t0 = time.time()
        with open(log_path, "w", encoding="utf-8") as f:
            p = subprocess.run([sys.executable, "-m", "corb", *command.split()], cwd=TOOLS, stdout=f, stderr=f)
        status = "done" if p.returncode == 0 else "failed"
        rel = os.path.relpath(log_path, VAR).replace("\\", "/")
        db.psql(f"UPDATE ops.job SET status = '{status}', finished_at = now(), exit_code = {p.returncode}, "
                f"log_path = '{rel}' WHERE job_id = {job_id};")
        log("jobs", level="info" if status == "done" else "error", msg=status, job_id=int(job_id), command=command,
            exit_code=p.returncode, seconds=round(time.time() - t0, 1))
        done.append(dict(job_id=int(job_id), command=command, status=status, seconds=round(time.time() - t0, 1)))
