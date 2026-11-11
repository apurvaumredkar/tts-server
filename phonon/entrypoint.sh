#!/bin/sh
# Start the ptts engine on 127.0.0.1:8880, wait until it answers, then serve the wrapper on 8002.
set -e

case "${PHONON_MODEL:-31m-en}" in
  hf://*|/*) MODEL="$PHONON_MODEL" ;;
  *) MODEL="hf://gradium/phonon-${PHONON_MODEL:-31m-en}" ;;
esac
# 31m-en -> en, 40m-fr -> fr, 40m-multilingual -> en (unconfirmed)
LANG_CODE="${MODEL##*phonon-}"; LANG_CODE="${LANG_CODE##*-}"
case "$LANG_CODE" in en|fr|de|es|pt) ;; *) LANG_CODE=en ;; esac

PTTS_MODEL="$MODEL" PTTS_LANG="${PTTS_LANG:-$LANG_CODE}" PTTS_QUANT="${PTTS_QUANT:-q8}" \
  ptts-openai-server --addr 127.0.0.1:8880 &

echo "waiting for engine ($MODEL, may download weights on first start)..."
python3 - <<'PY'
import time, urllib.request
for _ in range(900):
    try:
        urllib.request.urlopen("http://127.0.0.1:8880/v1/audio/voices", timeout=2)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        time.sleep(2)
raise SystemExit("engine did not become ready")
PY

exec uvicorn main:app --host 0.0.0.0 --port 8002
