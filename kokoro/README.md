# kokoro (tts-server/kokoro)

Self-hosted text-to-speech server built on [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (v1.0, ONNX) with FastAPI. It strips markdown and emoji from the input so the voice reads only words.

> **Designed to run on the NVIDIA Jetson Orin Nano Super.** It is developed and tested on that device (aarch64, JetPack 6 / L4T r36.4). The container is based on `nvcr.io/nvidia/l4t-jetpack` and uses `onnxruntime-gpu` from the Jetson AI Lab index to run on the Orin's GPU through CUDA. It falls back to CPU if CUDA is unavailable.

## Endpoints (port 8002)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check, returns `{"status":"ok"}` |
| POST | `/generate` | JSON in, `audio/wav` out (24 kHz, mono, 16-bit) |
| POST | `/stream` | Same JSON in, `audio/pcm` out: raw 16-bit little-endian mono PCM at 24 kHz (header `X-Sample-Rate: 24000`), streamed as each chunk is generated |

`/generate` and `/stream` share this request body:

```json
{ "text": "Hello there.", "voice": "bm_daniel", "speed": 1.0, "lang": "en-us" }
```

Only `text` is required. Code fences, links, URLs, headings, tables and emoji are removed before synthesis. If nothing speakable remains, the server returns `400`. The cleaning lives in `../common/speakable.py`, shared with the other engine.

## Models

Model files are not stored in this repo. Download them from the [kokoro-onnx releases](https://github.com/thewh1teagle/kokoro-onnx/releases) into `models/`:

```
models/
├── kokoro-v1.0.onnx
└── voices-v1.0.bin
```

## Run

Requires Docker with the NVIDIA runtime on the Jetson.

```bash
tts-server/run.sh kokoro
curl $TTS_HOST:8002/health
```

Phonon is the default engine (`tts-server/run.sh` with no arguments starts it); Kokoro is opt-in via `tts-server/run.sh kokoro`. Only one engine can bind port 8002, so the launcher stops the other first.

The compose build context is the parent `tts-server/` directory (`build: {context: .., dockerfile: kokoro/Dockerfile}`) so the image can include `common/`. To run it by hand: `docker compose -f tts-server/kokoro/docker-compose.yml up -d --build`.

The `models/` directory is bind-mounted into the container at `/app/models`.

## Example

```bash
curl -X POST $TTS_HOST:8002/generate \
  -H 'content-type: application/json' \
  -d '{"text":"The quick brown fox jumps over the lazy dog."}' \
  -o out.wav

# streaming: play raw PCM as it arrives
curl -N -X POST $TTS_HOST:8002/stream \
  -H 'content-type: application/json' \
  -d '{"text":"The quick brown fox jumps over the lazy dog."}' \
  | aplay -t raw -f S16_LE -r 24000 -c 1
```

## Notes

- `kokoro-onnx` is installed with `--no-deps` in the Dockerfile. It depends on CPU-only `onnxruntime`, which would overwrite `onnxruntime-gpu`. See `requirements.txt` and `overrides.txt`.
- On startup the log prints `Active providers:`. Check that it lists `CUDAExecutionProvider`.
- Pairs with [canary-stt-server](https://github.com/apurvaumredkar/canary-stt-server) for a fully local voice stack.
