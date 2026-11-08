#!/usr/bin/env bash
# INF-P5-T05: provision the infra host (Linux, 16-32 vCPU, 64 GB RAM, 1 TB NVMe; doc/infrascaleup.md §INF-P5).
# Run as root on a fresh Ubuntu 24.04 host: sudo REPO_URL=https://github.com/Atlas00000/cycleorb.git ./bootstrap.sh
# It never opens an inbound port: Postgres and Grafana bind to 127.0.0.1; reach them over SSH or Tailscale.
set -euo pipefail

REPO_URL=${REPO_URL:?set REPO_URL}
ROOT=${CORB_ROOT:-/opt/cycleorb}

apt-get update
apt-get install -y ca-certificates curl git python3 python3-venv postgresql-client
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

id corb >/dev/null 2>&1 || useradd --system --create-home --groups docker corb
if [ ! -d "$ROOT/.git" ]; then
  git clone "$REPO_URL" "$ROOT"
fi
chown -R corb:corb "$ROOT"

if [ ! -f "$ROOT/infra/.env" ]; then
  cp "$ROOT/infra/.env.example" "$ROOT/infra/.env"
  sed -i "s/^CORB_DB_PASSWORD=.*/CORB_DB_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=')/" "$ROOT/infra/.env"
  chmod 600 "$ROOT/infra/.env"
  chown corb:corb "$ROOT/infra/.env"
  echo "edit $ROOT/infra/.env (tester login) before the first tester job"
fi

cd "$ROOT/infra"
sudo -u corb docker compose up -d db
sudo -u corb docker compose --profile tools run --rm dbmate up
sudo -u corb docker compose --profile train build jobs
(cd "$ROOT/tools" && sudo -u corb python3 -m corb ops roles)   # stdlib only; needs docker exec, so on the host
sudo -u corb docker compose --profile obs up -d grafana

install -m 644 "$ROOT/infra/host/corb-worker.service" /etc/systemd/system/
install -m 644 "$ROOT/infra/host/corb-nightly.service" /etc/systemd/system/
install -m 644 "$ROOT/infra/host/corb-nightly.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now corb-worker.service corb-nightly.timer
echo "infra host ready: worker running, nightly timer enabled"
