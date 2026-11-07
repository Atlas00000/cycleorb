# INF-P5-T04: the corb job image (ingest, features, train, eval, tests). Base pinned by digest, libraries by
# requirements.lock. The repo is mounted at /repo at run time (the job runs the committed code it is given) and the
# var/ folder also at /corb/var (the path the loaders hand to psql \copy). DB access over the network:
# CORB_DB_HOST / CORB_DB_PORT (+ the credentials from infra/.env).
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client git \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /repo/tools
ENTRYPOINT ["python", "-m", "corb"]
