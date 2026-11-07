# INF-P2-T04: headless MT5 Strategy Tester under Wine + Xvfb.
# Build context is assembled by `python -m corb tester build` in var/tester/build/ (never committed):
#   Dockerfile, run_tester.sh, mt5/ (a copy of the workstation's MT5 install, so the container runs the same build).
# No credentials are baked in: the tester login comes from infra/.env into the per-run .ini at run time.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    WINEDEBUG=-all \
    WINEPREFIX=/wine \
    WINEARCH=win64

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget gnupg xvfb xauth winbind cabextract procps \
 && mkdir -pm755 /etc/apt/keyrings \
 && wget -qO /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
 && wget -qNP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources \
 && apt-get update \
 && apt-get install -y --install-recommends winehq-stable \
 && rm -rf /var/lib/apt/lists/*

# The Wine prefix is NOT initialised here: Wine 11 needs a socket call that Docker's default seccomp profile blocks,
# and RUN steps can't relax seccomp. `corb tester build` initialises the prefix in a one-off container started with
# --security-opt seccomp=unconfined and commits the result (tester containers run with the same option).
ENV WINEDLLOVERRIDES="mscoree,mshtml="

COPY mt5/ /opt/mt5/
COPY run_tester.sh /usr/local/bin/run_tester
RUN chmod +x /usr/local/bin/run_tester && wine --version > /opt/wine-version.txt

WORKDIR /opt/mt5
ENTRYPOINT ["run_tester"]
