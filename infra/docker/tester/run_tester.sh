#!/bin/sh
# One Strategy Tester job in the portable MT5 at /opt/mt5. `corb tester run` mounts per job:
#   /opt/mt5/run.ini (login + [Tester] job, ShutdownTerminal=1), MQL5/Experts/CycleORB (the .ex5),
#   MQL5/Profiles/Tester (presets), config/servers.dat, bases (history volume), Tester/logs, logs, reports,
#   and the Wine user's Common\Files (tester ledgers).
set -eu
timeout "${CORB_TESTER_TIMEOUT:-5400}" xvfb-run -a -s "-screen 0 1280x800x24" \
  wine /opt/mt5/terminal64.exe /portable '/config:Z:\opt\mt5\run.ini' || echo "terminal exit code $?"
wineserver -w || true
echo "wine: $(cat /opt/wine-version.txt)"
ls -1 /opt/mt5/Tester/logs 2>/dev/null || echo "no tester logs"
