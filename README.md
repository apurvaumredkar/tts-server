# tts-server

Self-hosted text-to-speech for the NVIDIA Jetson Orin Nano Super, with two interchangeable engines behind one HTTP API:

| Engine | Dir | Model | Runtime |
|---|---|---|---|
| **Phonon** (default) | [`phonon/`](phonon/) | Gradium [Phonon](https://gradium.ai/phonon) 31M English (40M variants optional) | Gradium `ptts-openai-server` (Rust), CPU, q8 |
| Kokoro | [`kokoro/`](kokoro/) | [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) v1.0 | ONNX Runtime GPU (CUDA) |

Both strip markdown and emoji before speaking (shared code in [`common/speakable.py`](common/speakable.py)), listen on port
8002, and return 24 kHz mono 16-bit audio. Only one runs at a time.

## Run

```bash
./run.sh                    # Phonon 31m-en (default)
./run.sh phonon 40m-fr      # another Phonon variant: 31m-en, 40m-en, 40m-fr, 40m-de, 40m-es, 40m-pt, 40m-multilingual
./run.sh kokoro             # Kokoro instead
./run.sh stop | status
```

`run.sh` binds to `$TTS_HOST`, which defaults to the machine's Tailscale IPv4 (`tailscale ip -4`), else `127.0.0.1`. Starting
one engine stops the other. Kokoro needs its model files in `kokoro/models/` (see [`kokoro/README.md`](kokoro/README.md));
Phonon downloads its weights from Hugging Face on first start. The 40M Phonon models are gated and need `HF_TOKEN`.

## API (both engines)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | `{"status":"ok"}` |
| POST | `/generate` | `{"text", "voice"?, "speed"?, "lang"?}` | `audio/wav`, whole clip |
| POST | `/stream` | same | `audio/pcm`: raw s16le mono, header `X-Sample-Rate: 24000`, sent as it is generated |

`text` is required; `400` if nothing speakable is left after cleaning. Phonon ignores `speed` and `lang` (the language comes
from the model variant) and maps Kokoro voice names such as `bm_daniel` to its `default` voice.

## Benchmarks

Jetson Orin Nano Super 8 GB, JetPack 6 (L4T r36.4), power mode `MAXN_SUPER`, measured 2026-11-11 with
[`bench/bench.py`](bench/bench.py). Six assistant-style sentences (27 to 180 characters), each engine with its default voice,
median of 3 runs after one warm-up request. Raw results: [`bench/results/`](bench/results/).

| | Phonon 31m-en | Kokoro v1.0 |
|---|---:|---:|
| Runs on | CPU (q8 weights) | GPU (CUDA) |
| **Time to first audio** (`/stream`, median) | **0.12 s** | 0.74 s |
| Real-time factor (`/generate`, median; lower is faster) | 0.24 | **0.18** |
| First request after start | 0.41 s | 0.39 s |
| Word error rate (TTS, then STT) | 2.0% | 2.0% |
| Container memory | **528 MiB** | 2.06 GiB |
| Image size | **310 MB** | 16 GB |
| Voices | 38 | 54 |
| Model licence | Apache 2.0 (40M variants: CC BY-NC 4.0) | Apache 2.0 |

Per sentence (Phonon / Kokoro):

| Chars | Audio length | Synthesis time | First audio |
|---:|---:|---:|---:|
| 27 | 2.1 s / 1.7 s | 0.52 s / 0.41 s | 0.11 s / 0.42 s |
| 42 | 2.6 s / 2.4 s | 0.64 s / 0.50 s | 0.11 s / 0.51 s |
| 74 | 4.2 s / 3.7 s | 0.96 s / 0.71 s | 0.13 s / 0.69 s |
| 91 | 4.8 s / 4.5 s | 1.16 s / 0.80 s | 0.14 s / 0.79 s |
| 98 | 5.5 s / 5.4 s | 1.27 s / 0.89 s | 0.14 s / 0.89 s |
| 180 | 11.3 s / 10.1 s | 2.53 s / 1.51 s | 0.10 s / 1.51 s |

What the numbers say:

- **Phonon starts talking about 6x sooner.** It streams audio frames as it decodes, so the first sound arrives in about
  0.1 s whatever the length. Kokoro's `create_stream` yields one chunk per phoneme batch, and a sentence under roughly a
  paragraph is a single batch, so its first audio arrives only when the whole clip is done.
- **Kokoro finishes a whole clip faster** on the GPU, but both run 4 to 6 times faster than real time, so playback never
  waits on either once it has started.
- **Phonon is far lighter**: CPU only, a quarter of the memory, and a 310 MB image, which leaves the GPU free for STT and
  the LLM.
- **Intelligibility is the same.** Each clip was transcribed by [canary-stt-server](https://github.com/apurvaumredkar/canary-stt-server)
  (Canary 1B v2) and scored against the input, with digits normalized to words. The only error on either engine is the
  STT writing "windowsill" as "window sill". This measures whether the words come through, not how natural the voice
  sounds; that comparison was made by ear, and is why Phonon is the default.

Reproduce, with an engine running and an STT server that accepts 16 kHz s16le PCM on `/transcribe`:

```bash
python3 bench/bench.py http://$TTS_HOST:8002 phonon --stt http://<stt-host>:8001/transcribe --json bench/results/phonon.json
```

## Layout

```
tts-server/
├── run.sh            # engine launcher
├── common/           # speakable(): markdown/emoji stripping shared by both engines
├── phonon/           # FastAPI wrapper around ptts-openai-server (default engine)
├── kokoro/           # FastAPI + kokoro-onnx on CUDA
└── bench/            # benchmark script and results
```

Docker builds use `tts-server/` as the context, so each engine's image can include `common/`.
