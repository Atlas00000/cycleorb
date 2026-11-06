"""Workspace locations. Override the external ones with CORB_TERMINAL_DIR, CORB_COMMON_DIR, CORB_OUROBOROS_DIR."""
import os
import subprocess

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(TOOLS)
INFRA = os.path.join(REPO, "infra")
VAR = os.path.join(REPO, "var")
RUNS = os.path.join(REPO, "tester", "aos", "runs")
TERMINAL = os.environ.get("CORB_TERMINAL_DIR") or os.path.normpath(os.path.join(REPO, "..", "..", ".."))
COMMON = os.environ.get("CORB_COMMON_DIR") or os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal",
                                                           "Common", "Files")
OUROBOROS = os.environ.get("CORB_OUROBOROS_DIR")

PLACEHOLDERS = {"%REPO%": REPO, "%TERMINAL%": TERMINAL, "%COMMON%": COMMON}


def resolve(location):
    """Expand a %PLACEHOLDER% path. Returns None when it needs an unset root (e.g. %OUROBOROS%)."""
    roots = dict(PLACEHOLDERS, **({"%OUROBOROS%": OUROBOROS} if OUROBOROS else {}))
    for key, root in roots.items():
        if location.startswith(key):
            return os.path.normpath(root + location[len(key):])
    return None


def portable(path):
    """Absolute path -> %PLACEHOLDER% form, so committed files carry no user-specific paths."""
    full = os.path.normcase(os.path.abspath(path))
    for key, root in sorted(PLACEHOLDERS.items(), key=lambda kv: -len(kv[1])):
        r = os.path.normcase(os.path.abspath(root))
        if full == r or full.startswith(r + os.sep):
            return key + os.path.abspath(path)[len(r):].replace("\\", "/")
    return path.replace("\\", "/")


def git_info():
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return dict(head=git("rev-parse", "HEAD"), tag_infra_p0=git("rev-list", "-n", "1", "infra-p0"),
                dirty=bool(git("status", "--porcelain", "--untracked-files=no")))
