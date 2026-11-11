#!/usr/bin/env python3
"""Benchmark a running TTS engine (kokoro or phonon) over the shared HTTP contract.

Measures, per sentence:
  - /generate wall time and real-time factor (RTF = synthesis time / audio length; < 1 is faster than real time)
  - /stream time to first audio byte (what a listener waits before hearing anything)
  - intelligibility: the /generate audio is transcribed by an STT server (canary-stt-server /transcribe,
    16 kHz s16le PCM in) and scored as word error rate (WER) against the input text

Usage: bench.py URL LABEL [--stt URL] [--runs N] [--voice V] [--json out.json]
Needs numpy and scipy. The engine must be running; nothing is started here.
"""
import argparse
import io
import json
import re
import statistics
import time
import urllib.request
import wave

import numpy as np
from scipy.signal import resample_poly

# No digits or abbreviations, so the transcript can be compared word for word.
SENTENCES = [
    "Sure, I can help with that.",
    "The lights in the living room are now off.",
    "It looks like you have three unread emails from your manager this morning.",
    "Traffic is light on the way to the office, so you should get there in about twenty minutes.",
    "The quick brown fox jumps over the lazy dog while the sleepy cat watches from the warm windowsill.",
    "I found a nice Italian restaurant nearby. It has great reviews, it is open until eleven tonight, "
    "and they take reservations online, so I can book a table for two if you would like.",
]


def post(url: str, body: dict, stream: bool = False):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        if not stream:
            data = r.read()
            return data, time.perf_counter() - t0, None
        first, chunks = None, []
        while chunk := r.read1(4096):
            if first is None:
                first = time.perf_counter() - t0
            chunks.append(chunk)
        return b"".join(chunks), time.perf_counter() - t0, first


def wav_to_pcm(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "expected mono 16-bit WAV"
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"), w.getframerate()


def transcribe(stt: str, pcm: np.ndarray, rate: int) -> str:
    audio16 = resample_poly(pcm.astype(np.float32), 16000, rate)
    body = np.clip(audio16, -32768, 32767).astype("<i2").tobytes()
    req = urllib.request.Request(stt, body, {"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["text"]


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
         "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _spell(n: int) -> str:
    """0-99 as words, so STT digits ("20") match the spoken reference ("twenty")."""
    return _ONES[n] if n < 20 else _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])


def words(text: str) -> list[str]:
    text = re.sub(r"\b\d{1,2}\b", lambda m: _spell(int(m.group())), text.lower().replace("-", " "))
    return re.sub(r"[^a-z' ]", " ", text).split()


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)], len(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("label")
    ap.add_argument("--stt", default="")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    def body(text):
        return {"text": text, **({"voice": a.voice} if a.voice else {})}

    # Warm up (first request pays model/session start-up).
    t0 = time.perf_counter()
    post(f"{a.url}/generate", body("Warming up."))
    cold = time.perf_counter() - t0

    rows, errs, ref_words, transcripts = [], 0, 0, []
    for text in SENTENCES:
        gen_t, ttfb, stream_t = [], [], []
        for _ in range(a.runs):
            data, t, _ = post(f"{a.url}/generate", body(text))
            gen_t.append(t)
            raw, t, first = post(f"{a.url}/stream", body(text), stream=True)
            stream_t.append(t)
            ttfb.append(first)
        pcm, rate = wav_to_pcm(data)
        dur = len(pcm) / rate
        assert len(raw) // 2 > 0, "stream returned no audio"
        row = {
            "chars": len(text),
            "audio_s": round(dur, 2),
            "generate_s": round(statistics.median(gen_t), 3),
            "rtf": round(statistics.median(gen_t) / dur, 3),
            "stream_ttfb_s": round(statistics.median(ttfb), 3),
            "stream_total_s": round(statistics.median(stream_t), 3),
            "rate": rate,
        }
        if a.stt:
            hyp = transcribe(a.stt, pcm, rate)
            e, n = wer(text, hyp)
            errs, ref_words = errs + e, ref_words + n
            row["wer"] = round(e / n, 3)
            transcripts.append({"ref": text, "hyp": hyp})
        rows.append(row)
        print(json.dumps(row), flush=True)

    summary = {
        "engine": a.label,
        "cold_first_request_s": round(cold, 3),
        "median_rtf": round(statistics.median(r["rtf"] for r in rows), 3),
        "median_stream_ttfb_s": round(statistics.median(r["stream_ttfb_s"] for r in rows), 3),
        "wer": round(errs / ref_words, 4) if a.stt else None,
        "rows": rows,
        "transcripts": transcripts,
    }
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rows", "transcripts")}))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
