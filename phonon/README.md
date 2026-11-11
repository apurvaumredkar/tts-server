# phonon

TTS engine for Max using Gradium's Phonon, with the same HTTP contract as `kokoro/` (port 8002), so max-agent needs no change.

## Why not Ollama
The Ollama build of Phonon is Apple Silicon only (Linux is "coming soon"), so it cannot run on this Jetson (Linux aarch64).
Instead this runs Gradium's open-source runtime, https://github.com/gradium-ai/xn-ptts (Rust, no PyTorch), via its
`ptts-openai-server` image `ghcr.io/gradium-ai/ptts-openai-server:0.7.0` (pinned; CPU build for amd64 and arm64, no weights).
`entrypoint.sh` starts the engine on `127.0.0.1:8880`, waits for it, then serves `main.py` (FastAPI) on 8002. If the engine is
down, the endpoints return 503.

## Models
Set `PHONON_MODEL` to a variant (default `31m-en`); weights download from Hugging Face on first start into the `phonon-cache` volume.

| Variant | Repo | License | Notes |
|---|---|---|---|
| `31m-en` | gradium/phonon-31m-en | Apache 2.0 | public |
| `40m-en`, `40m-fr`, `40m-de`, `40m-es`, `40m-pt`, `40m-multilingual` | gradium/phonon-40m-* | CC BY-NC 4.0 (non-commercial) | gated: needs `HF_TOKEN` |

Engine language (`PTTS_LANG`) is derived from the variant (`multilingual` falls back to `en`; override with `PTTS_LANG`).
Voices: `default`, plus catalog voices (Zoey, Easton, Freya, Hugh; `GET /v1/audio/voices` on the engine). Kokoro voice names
(`bm_`, `af_`, ...) fall back to `default`.

## Endpoints
Body: `{"text": str, "voice": "default", "speed": 1.0, "lang": "en-us"}`. Text is cleaned with `common.speakable.speakable`; empty gives 400.
`speed` is ignored (the engine only supports 1.0) and `lang` is ignored (language is fixed by the loaded model).

| Endpoint | Returns |
|---|---|
| `GET /health` | `{"status":"ok"}` |
| `POST /generate` | `audio/wav` (16-bit mono 24 kHz), complete |
| `POST /stream` | `audio/pcm` (raw s16le mono 24 kHz) streamed as generated; header `X-Sample-Rate: 24000` |

```
curl -X POST http://$TTS_HOST:8002/generate -H 'Content-Type: application/json' -d '{"text":"Hello there."}' -o out.wav
curl -N -X POST http://$TTS_HOST:8002/stream -H 'Content-Type: application/json' -d '{"text":"Hello there."}' | aplay -r 24000 -f S16_LE -c 1
```

## Run
Port 8002 is the same as kokoro: run only one TTS engine at a time.

```
tts-server/run.sh phonon [variant]
# or directly
PHONON_MODEL=31m-en docker compose -f phonon/docker-compose.yml up -d --build
HF_TOKEN=... PHONON_MODEL=40m-en docker compose -f phonon/docker-compose.yml up -d --build   # gated model
```

The build context is `tts-server/` (the Dockerfile copies `common/` and `phonon/`). In the container the layout is
`/app/common/speakable.py` and `/app/main.py`, so `from common.speakable import speakable` works there; to run `main.py`
locally, start it from `tts-server/` with `phonon/` on the path (e.g. `PYTHONPATH=. uvicorn --app-dir phonon main:app`).

## CPU vs CUDA
CPU only. The published image is CPU; a CUDA build is not documented, so `docker-compose.yml` does not use `runtime: nvidia`.
A 31M model is fine on CPU. The engine runs one generation at a time (extra concurrent requests get 429 from the engine, surfaced as 429).
