#!/usr/bin/env bash
# Launcher for the TTS engines. Only one may run: both bind $TTS_HOST:8002.
# TTS_HOST defaults to this machine's Tailscale IPv4 (falls back to 127.0.0.1).
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

export TTS_HOST="${TTS_HOST:-$(tailscale ip -4 2>/dev/null | head -1 || true)}"
export TTS_HOST="${TTS_HOST:-127.0.0.1}"

VARIANTS="31m-en 40m-en 40m-fr 40m-de 40m-es 40m-pt 40m-multilingual"

usage() {
  cat >&2 <<USAGE
Usage:
  ./run.sh                      # same as: ./run.sh phonon (phonon is the default engine)
  ./run.sh phonon [VARIANT]     # start phonon; VARIANT: ${VARIANTS// /, } (default 31m-en)
  ./run.sh kokoro               # start kokoro (opt-in) on \$TTS_HOST:8002
  ./run.sh stop                 # stop whichever engine is running
  ./run.sh status               # show which engine containers are up
USAGE
  exit 2
}

compose() { docker compose -f "$1/docker-compose.yml" "${@:2}"; }

# Remove by container name: the live container may have been started with plain `docker run`,
# which `docker compose down` would not stop.
stop_engine() { docker rm -f "$1-tts" >/dev/null 2>&1 || true; }

cmd="${1:-phonon}"
case "$cmd" in
  kokoro)
    [[ $# -le 1 ]] || usage
    stop_engine phonon
    compose kokoro up -d --build
    ;;
  phonon)
    [[ $# -le 2 ]] || usage
    variant="${2:-31m-en}"
    [[ " $VARIANTS " == *" $variant "* ]] || usage
    stop_engine kokoro
    PHONON_MODEL="$variant" compose phonon up -d --build
    ;;
  stop)
    [[ $# -le 1 ]] || usage
    stop_engine kokoro
    stop_engine phonon
    exit 0
    ;;
  status)
    docker ps --filter name=kokoro-tts --filter name=phonon-tts
    exit 0
    ;;
  *) usage ;;
esac

echo "http://$TTS_HOST:8002/health"
