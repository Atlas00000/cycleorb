"""INF-P3-T02: bar export from the broker history cache, without touching the workstation terminal.

prepare()  portable MT5 instance in var/mt5_export: a copy of the install, servers.dat, the cached symbol list and
           the 2020+ M1 history of the export symbols; the export script compiled by the instance's MetaEditor
export()   start it headless ([StartUp] script, ShutdownTerminal=1, MaxBars raised); it reads the local history
           (no broker login needed) and writes Common\\Files\\CycleORB\\bars\\<symbol>\\<tf>\\<year>.csv
lake()     CSV -> var/lake/bars/<symbol>/<tf>/<year>.parquet (time as UTC), features.bar_index; calendar snapshot
"""
import csv
import glob
import os
import shutil
import subprocess
from datetime import datetime, timezone

from corb import db, landing
from corb.inventory import sha256
from corb.paths import COMMON, REPO, TERMINAL, TOOLS, VAR
from corb.tester import _credentials, mt5_install

INSTANCE = os.path.join(VAR, "mt5_export")
LAKE = os.path.join(VAR, "lake", "bars")
EXPORT_DIR = os.path.join(COMMON, "CycleORB", "bars")
SCRIPT = os.path.join(TOOLS, "mql5", "CycleORB_ExportBars.mq5")
SYMBOLS = ["EURUSD", "DE30", "JPN225", "UK100", "SPX500", "USDJPY", "GBPUSD", "Apple", "Microsoft", "Exxon", "NVDA",
           "Tesla"]
FROM_YEAR = 2020
SERVER = "YWO-Trade"


def prepare():
    if not os.path.exists(os.path.join(INSTANCE, "terminal64.exe")):
        shutil.copytree(mt5_install(), INSTANCE, dirs_exist_ok=True)
    os.makedirs(os.path.join(INSTANCE, "config"), exist_ok=True)
    shutil.copyfile(os.path.join(TERMINAL, "config", "servers.dat"), os.path.join(INSTANCE, "config", "servers.dat"))
    src_bases = os.path.join(TERMINAL, "bases", SERVER)
    dst_bases = os.path.join(INSTANCE, "bases", SERVER)
    shutil.copytree(os.path.join(src_bases, "symbols"), os.path.join(dst_bases, "symbols"), dirs_exist_ok=True)
    copied, locked = 0, []
    for sym in SYMBOLS:
        for f in glob.glob(os.path.join(src_bases, "history", sym, "*.hcc")):
            year = os.path.splitext(os.path.basename(f))[0]
            if year.isdigit() and int(year) >= FROM_YEAR:
                dst = os.path.join(dst_bases, "history", sym, os.path.basename(f))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(f):
                        shutil.copyfile(f, dst)
                    copied += 1
                except PermissionError:   # the workstation terminal holds its current-year file exclusively
                    locked.append(f"{sym}/{year}")
    script_dir = os.path.join(INSTANCE, "MQL5", "Scripts", "CycleORB")
    os.makedirs(script_dir, exist_ok=True)
    target = os.path.join(script_dir, os.path.basename(SCRIPT))
    shutil.copyfile(SCRIPT, target)
    log = os.path.join(INSTANCE, "compile.log")
    subprocess.run([os.path.join(INSTANCE, "MetaEditor64.exe"), "/portable", f"/compile:{target}", f"/log:{log}"],
                   capture_output=True, timeout=300)
    ex5 = target[:-4] + ".ex5"
    with open(log, encoding="utf-16", errors="replace") as f:
        result = f.read().strip().splitlines()[-1:] or ["no compile log"]
    return dict(instance=INSTANCE, history_files=copied, locked_by_terminal=locked, compiled=os.path.exists(ex5),
                compile_log=result[0])


def export(timeout=3600, chart_symbol=None):
    """The script starts only once its chart has data: open it on a symbol whose current-year history was copied."""
    login, password, _ = _credentials()   # a login without a password makes MT5 pop its login dialog
    if chart_symbol is None:
        year = str(datetime.now().year)
        hist = os.path.join(INSTANCE, "bases", SERVER, "history")
        chart_symbol = next((s for s in SYMBOLS if os.path.exists(os.path.join(hist, s, f"{year}.hcc"))), "EURUSD")
    ini = os.path.join(INSTANCE, "export.ini")
    with open(ini, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f"[Common]\nLogin={login}\nPassword={password}\nServer={SERVER}\nProxyEnable=0\nNewsEnable=0\n\n"
                f"[Charts]\nMaxBars=50000000\n\n"
                f"[StartUp]\nScript=CycleORB\\CycleORB_ExportBars\nSymbol={chart_symbol}\nPeriod=H1\n"
                f"ShutdownTerminal=1\n")
    if os.path.isdir(EXPORT_DIR):
        shutil.rmtree(EXPORT_DIR)
    started = datetime.now(timezone.utc)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7   # SW_SHOWMINNOACTIVE: minimised, never takes focus from the user
    try:
        p = subprocess.run([os.path.join(INSTANCE, "terminal64.exe"), "/portable", f"/config:{ini}"], timeout=timeout,
                           startupinfo=si)
    finally:
        os.remove(ini)   # it holds the password
    manifest = os.path.join(EXPORT_DIR, "manifest.csv")
    rows = []
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8", errors="replace") as f:
            rows = list(csv.DictReader(f))
    return dict(exit=p.returncode, seconds=(datetime.now(timezone.utc) - started).seconds, files=len(rows),
                bars=sum(int(r["rows"]) for r in rows), manifest=rows)


def lake():
    import pandas as pd
    os.makedirs(LAKE, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    index = []
    for path in sorted(glob.glob(os.path.join(EXPORT_DIR, "*", "*", "*.csv"))):
        sym, tf, year = path.split(os.sep)[-3], path.split(os.sep)[-2], os.path.splitext(os.path.basename(path))[0]
        df = pd.read_csv(path)
        df["time"] = pd.to_datetime(df["time"], format="%Y.%m.%d %H:%M:%S").dt.tz_localize("UTC")  # server = UTC
        out = os.path.join(LAKE, sym, tf, f"{year}.parquet")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_parquet(out, index=False)
        index.append(dict(symbol=sym, tf=tf, year=int(year), rows=len(df), first_bar=df["time"].min().isoformat(),
                          last_bar=df["time"].max().isoformat(), lake_path=os.path.relpath(out, VAR).replace("\\", "/"),
                          sha256=sha256(path), source="mt5_export_ywo", exported_at=now))
    landing.land(sorted(glob.glob(os.path.join(EXPORT_DIR, "*", "*", "*.csv"))), "mt5_export")
    cal = os.path.join(COMMON, "CycleORB", "events.csv")
    snap = None
    if os.path.exists(cal):
        landing.land([cal], "calendar")
        with open(cal, encoding="utf-8", errors="replace") as f:
            ev = list(csv.reader(f))[1:]
        times = sorted(r[0] for r in ev if r)
        snap = dict(snapshot_sha256=sha256(cal), events=len(ev), first_event=times[0] if times else None,
                    last_event=times[-1] if times else None, taken_at=now)
    _load(index, snap)
    return dict(files=len(index), bars=sum(i["rows"] for i in index), calendar=snap)


def _load(index, snap):
    stage = os.path.join(VAR, "stage")
    os.makedirs(stage, exist_ok=True)
    cols = ["symbol", "tf", "year", "rows", "first_bar", "last_bar", "lake_path", "sha256", "source", "exported_at"]
    with open(os.path.join(stage, "bar_index.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(index)
    sql = ["BEGIN;", "DELETE FROM features.bar_index WHERE source = 'mt5_export_ywo';",
           f"\\copy features.bar_index ({', '.join(cols)}) FROM '/corb/var/stage/bar_index.csv' "
           f"WITH (FORMAT csv, HEADER true)"]
    if snap:
        first = "NULL" if not snap["first_event"] else f"'{snap['first_event'].replace('.', '-')}'"
        last = "NULL" if not snap["last_event"] else f"'{snap['last_event'].replace('.', '-')}'"
        sql.append(f"INSERT INTO features.calendar_snapshot VALUES ('{snap['snapshot_sha256']}', {snap['events']}, "
                   f"{first}, {last}, '{snap['taken_at']}') ON CONFLICT DO NOTHING;")
    sql.append("COMMIT;")
    db.psql("\n".join(sql) + "\n")
