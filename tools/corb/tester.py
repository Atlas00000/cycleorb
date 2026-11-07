"""INF-P2-T04: MT5 Strategy Tester in Docker (Wine + Xvfb).

build    assemble var/tester/build (Dockerfile, run_tester.sh, a copy of the workstation's MT5 install) and build
         the image cycleorb-tester:<mt5 build>
exp      write the EXP- presets (Presets/EXP/) and tester inis (tester/exp/): the P1obs observe presets with the run tag
         EXP. EA logic unchanged; the ledger is on so every run has its ledger as well as its journal
run      one container per ini (up to --parallel at once), each with its own job folder under var/tester/jobs/:
         run.ini (login from infra/.env + the [Tester] job), the .ex5, the preset, servers.dat; outputs are the tester
         journal, terminal log, report and Common\\Files ledgers. The journal is parsed into var/tester/parsed/
parity   each parsed EXP run vs the committed native run with the same events (the v1.11 P1obs observe run):
         final balance and events.csv bytes must be identical
"""
import configparser
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from corb.inventory import sha256
from corb.paths import INFRA, REPO, RUNS, TERMINAL, TOOLS, VAR
from corb.textio import read_text

IMAGE = "cycleorb-tester"
BASES_VOLUME = "cycleorb_mt5_bases"
WINE_COMMON = "/wine/drive_c/users/root/AppData/Roaming/MetaQuotes/Terminal/Common/Files"
TV = os.path.join(VAR, "tester")
EXP_PRESETS = os.path.join(REPO, "Presets", "EXP")
EXP_INIS = os.path.join(REPO, "tester", "exp")
SECCOMP = ["--security-opt", "seccomp=unconfined"]   # Wine 11 needs a socket call the default profile blocks
ASSETS = ["DE40", "EURUSD-LON0700", "EURUSD-NY", "JP225", "UK100", "US500", "CTRL-AAPL", "CTRL-MSFT", "CTRL-XOM"]


def _docker(args, check=True):
    p = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise RuntimeError(f"docker {' '.join(args[:2])} failed:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return p.stdout


def mt5_install():
    """The terminal's install folder, from its data folder's origin.txt."""
    return read_text(os.path.join(TERMINAL, "origin.txt")).strip()


def mt5_build(install):
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-Item '{os.path.join(install, 'terminal64.exe')}').VersionInfo.FileVersion"],
                         capture_output=True, text=True).stdout.strip()
    return out.split(".")[-1] or "unknown"


def build():
    install = mt5_install()
    ctx = os.path.join(TV, "build")
    os.makedirs(ctx, exist_ok=True)
    for name in ("Dockerfile", "run_tester.sh"):
        with open(os.path.join(INFRA, "docker", "tester", name), encoding="utf-8") as f:
            text = f.read().replace("\r\n", "\n")
        with open(os.path.join(ctx, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if os.path.isdir(os.path.join(ctx, "mt5")):
        shutil.rmtree(os.path.join(ctx, "mt5"))
    shutil.copytree(install, os.path.join(ctx, "mt5"))
    tag = f"{IMAGE}:{mt5_build(install)}"
    p = subprocess.run(["docker", "build", "-t", f"{IMAGE}:base", ctx], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError(p.stderr[-3000:])
    # initialise the Wine prefix with seccomp relaxed (see the Dockerfile), then commit it as the runnable image
    _docker(["rm", "-f", "cycleorb-tester-init"], check=False)
    _docker(["run", "--name", "cycleorb-tester-init", *SECCOMP, "--entrypoint", "sh", f"{IMAGE}:base", "-c",
             "xvfb-run -a wineboot --init >/tmp/wineboot.log 2>&1; wineserver -w; test -d /wine/drive_c/windows"])
    _docker(["commit", "--change", 'ENTRYPOINT ["run_tester"]', "cycleorb-tester-init", tag])
    _docker(["rm", "cycleorb-tester-init"])
    _docker(["tag", tag, f"{IMAGE}:latest"])
    wine = _docker(["run", "--rm", "--entrypoint", "cat", tag, "/opt/wine-version.txt"]).strip()
    return dict(image=tag, mt5_install=install, wine=wine,
                image_id=_docker(["image", "inspect", "-f", "{{.Id}}", tag]).strip())


def make_exp():
    """EXP presets + inis from the archived P1obs observe presets (same inputs, run tag EXP)."""
    os.makedirs(EXP_PRESETS, exist_ok=True)
    os.makedirs(EXP_INIS, exist_ok=True)
    made = []
    for asset in ASSETS:
        src_set = os.path.join(REPO, "Presets", "AOS", "archive", f"AOS-P1-T06_L6L1_observeAll_{asset}.set")
        src_ini = os.path.join(REPO, "tester", "aos", f"AOS-P1-T06_observeAll_{asset}.ini")
        name = f"EXP-P2-T04_baseline_{asset}"
        body = read_text(src_set).replace("\r\n", "\n").replace("InpAosRunTag=P1obs", "InpAosRunTag=EXP")
        header = (f"; {name}: export preset for the tester-container parity test (INF-P2-T04). Copy of "
                  f"AOS-P1-T06_L6L1_observeAll_{asset}.set with InpAosRunTag=EXP. EA logic unchanged.\n")
        with open(os.path.join(EXP_PRESETS, name + ".set"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(header + body)
        cp = configparser.ConfigParser(interpolation=None)
        cp.optionxform = str
        cp.read(src_ini, encoding="utf-8")
        cp["Tester"]["ExpertParameters"] = f"ORB\\EXP\\{name}.set"
        cp["Tester"]["Report"] = f"reports\\{name}.htm"
        with open(os.path.join(EXP_INIS, name + ".ini"), "w", encoding="utf-8", newline="\r\n") as f:
            cp.write(f, space_around_delimiters=False)
        made.append(name)
    return made


def _credentials():
    env = {}
    path = os.path.join(INFRA, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            env.update(line.strip().split("=", 1) for line in f if "=" in line and not line.startswith("#"))
    env.update({k: v for k, v in os.environ.items() if k.startswith("CORB_MT5_")})
    missing = [k for k in ("CORB_MT5_LOGIN", "CORB_MT5_PASSWORD") if not env.get(k)]
    if missing:
        raise RuntimeError(f"set {', '.join(missing)} in infra/.env (a YWO-Trade demo or investor login, never live)")
    return env["CORB_MT5_LOGIN"], env["CORB_MT5_PASSWORD"], env.get("CORB_MT5_SERVER", "YWO-Trade")


def _prepare(ini_path, creds):
    name = os.path.splitext(os.path.basename(ini_path))[0]
    job = os.path.join(TV, "jobs", name)
    if os.path.isdir(job):
        shutil.rmtree(job)
    for sub in ("presets", "logs", "terminal_logs", "reports", "common", "ea"):
        os.makedirs(os.path.join(job, sub), exist_ok=True)
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(ini_path, encoding="utf-8")
    preset_rel = cp["Tester"]["ExpertParameters"]
    preset = next(iter(glob.glob(os.path.join(REPO, "Presets", "**", os.path.basename(preset_rel)), recursive=True)))
    dest = os.path.join(job, "presets", *preset_rel.split("\\"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(preset, dest)
    shutil.copyfile(os.path.join(REPO, "CycleORB.ex5"), os.path.join(job, "ea", "CycleORB.ex5"))
    login, password, server = creds
    out = configparser.ConfigParser(interpolation=None)
    out.optionxform = str
    out["Common"] = dict(Login=login, Password=password, Server=server, ProxyEnable="0", NewsEnable="0")
    out["Tester"] = dict(cp["Tester"])
    out["Tester"]["ShutdownTerminal"] = "1"
    with open(os.path.join(job, "run.ini"), "w", encoding="utf-8", newline="\r\n") as f:
        out.write(f, space_around_delimiters=False)
    return name, job


def _run_job(name, job, image, timeout):
    m = lambda host, cont, ro=False: ["-v", f"{host}:{cont}{':ro' if ro else ''}"]
    args = ["run", "--rm", "--name", f"cycleorb-tester-{name.lower()}", *SECCOMP,
            "-e", f"CORB_TESTER_TIMEOUT={timeout}"]
    args += m(os.path.join(job, "run.ini"), "/opt/mt5/run.ini", True)
    args += m(os.path.join(job, "ea"), "/opt/mt5/MQL5/Experts/CycleORB", True)
    args += m(os.path.join(job, "presets"), "/opt/mt5/MQL5/Profiles/Tester", True)
    args += m(os.path.join(TERMINAL, "config", "servers.dat"), "/opt/mt5/config/servers.dat", True)
    args += m(BASES_VOLUME, "/opt/mt5/bases")
    args += m(os.path.join(job, "logs"), "/opt/mt5/Tester/logs")
    args += m(os.path.join(job, "terminal_logs"), "/opt/mt5/logs")
    args += m(os.path.join(job, "reports"), "/opt/mt5/reports")
    args += m(os.path.join(job, "common"), WINE_COMMON)
    p = subprocess.run(["docker", *args, image], capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(job, "container.log"), "w", encoding="utf-8") as f:
        f.write(p.stdout + "\n" + p.stderr)
    journals = sorted(glob.glob(os.path.join(job, "logs", "*.log")))
    parsed = os.path.join(TV, "parsed", name)
    if os.path.isdir(parsed):
        shutil.rmtree(parsed)
    os.makedirs(parsed, exist_ok=True)
    for j in journals:
        subprocess.run([sys.executable, os.path.join(TOOLS, "corb_parse.py"), j, "--out", parsed], cwd=TOOLS,
                       capture_output=True, text=True)
    runs = [d for d in glob.glob(os.path.join(parsed, "*")) if os.path.isdir(d)]
    for d in runs:
        for kind in ("decisions", "events", "shadow"):
            src = glob.glob(os.path.join(job, "common", "CycleORB", f"*_EXP_{kind}.csv"))
            if src:
                shutil.copyfile(src[0], os.path.join(d, f"ledger_{kind}.csv"))
    return dict(name=name, exit=p.returncode, journals=len(journals), runs=[os.path.basename(d) for d in runs])


def run(inis, parallel=1, timeout=5400):
    creds = _credentials()
    image = f"{IMAGE}:latest"
    _docker(["volume", "create", BASES_VOLUME])
    jobs = [_prepare(i, creds) for i in inis]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return list(pool.map(lambda nj: _run_job(nj[0], nj[1], image, timeout), jobs))


def parity():
    """Each parsed EXP run vs the committed native P1obs run of the same asset (same events by construction)."""
    from corb.baseline import check
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        assets = json.load(f)["assets"]
    checks = []
    for asset in ASSETS:
        parsed = glob.glob(os.path.join(TV, "parsed", f"EXP-P2-T04_baseline_{asset}", "*"))
        native = os.path.join(RUNS, assets[asset]["run_id"] + "_P1obs")
        if not os.path.isdir(native):
            native = os.path.join(RUNS, assets[asset]["run_id"])
        if not parsed:
            checks.append(check(f"{asset}.container_run_present", True, False, 0))
            continue
        with open(os.path.join(native, "meta.json"), encoding="utf-8") as f:
            want = json.load(f)
        with open(os.path.join(parsed[0], "meta.json"), encoding="utf-8") as f:
            got = json.load(f)
        checks.append(check(f"{asset}.final_balance", want["final"], got["final"], 0.005))
        checks.append(check(f"{asset}.n_events", want["n_events"], got["n_events"], 0))
        checks.append(check(f"{asset}.events_byte_identical", sha256(os.path.join(native, "events.csv")),
                            sha256(os.path.join(parsed[0], "events.csv")), 0))
    return checks
