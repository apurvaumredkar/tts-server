import io
import wave

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from common.speakable import speakable

ENGINE = "http://127.0.0.1:8880/v1/audio/speech"
SAMPLE_RATE = 24000
DEFAULT_VOICE = "default"
KOKORO_PREFIXES = ("af_", "am_", "bf_", "bm_", "ef_", "em_", "ff_", "hf_", "hm_", "if_", "im_", "jf_", "jm_", "pf_", "pm_", "zf_", "zm_")

app = FastAPI()


@app.get("/health")
async def health():
    # Report the engine too, so the container healthcheck catches a dead ptts process.
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            await client.get("http://127.0.0.1:8880/v1/audio/voices")
    except httpx.TransportError:
        raise engine_down()
    return {"status": "ok"}


class GenerateRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    speed: float = 1.0  # ignored: the engine only supports 1.0
    lang: str = "en-us"  # ignored: language is fixed by the loaded model


def prepare(req: GenerateRequest):
    text = speakable(req.text)
    if not text:
        raise HTTPException(400, "nothing to say after removing markdown and emoji")
    voice = req.voice
    if not voice or voice.lower().startswith(KOKORO_PREFIXES):
        voice = DEFAULT_VOICE  # kokoro voice names do not exist here
    return {"input": text, "voice": voice, "response_format": "pcm"}


def engine_down():
    return HTTPException(503, "phonon engine is not available")


@app.post("/generate")
async def generate_voice(req: GenerateRequest):
    body = prepare(req)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(ENGINE, json=body)
    except httpx.TransportError:
        raise engine_down()
    if r.status_code != 200:
        raise HTTPException(r.status_code if r.status_code < 500 else 502, r.text[:200])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(r.content)
    return Response(content=buffer.getvalue(), media_type="audio/wav")


@app.post("/stream")
async def stream_voice(req: GenerateRequest):
    body = prepare(req)
    client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=5))
    try:
        upstream = await client.send(client.build_request("POST", ENGINE, json=body), stream=True)
    except httpx.TransportError:
        await client.aclose()
        raise engine_down()
    if upstream.status_code != 200:
        detail = (await upstream.aread()).decode(errors="replace")[:200]
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code if upstream.status_code < 500 else 502, detail)

    async def chunks():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        except httpx.TransportError:
            pass  # engine died mid-stream: end the audio
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(chunks(), media_type="audio/pcm", headers={"X-Sample-Rate": str(SAMPLE_RATE)})
