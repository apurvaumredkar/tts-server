import io

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import onnxruntime as ort
from kokoro_onnx import Kokoro
import soundfile as sf

from common.speakable import speakable

app = FastAPI()

MODEL = "models/kokoro-v1.0.onnx"
VOICES = "models/voices-v1.0.bin"

so = ort.SessionOptions()
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

providers = [
    (
        "CUDAExecutionProvider",
        {
            "device_id": 0,
            "cudnn_conv_algo_search": "DEFAULT",
        },
    ),
    "CPUExecutionProvider",
]

session = ort.InferenceSession(MODEL, sess_options=so, providers=providers)
print("Active providers:", session.get_providers())


kokoro = Kokoro.from_session(session, VOICES)


@app.get("/health")
async def health():
    return {"status": "ok"}


class GenerateRequest(BaseModel):
    text: str
    voice: str = "bm_daniel"
    speed: float = 1.0
    lang: str = "en-us"


@app.post("/generate")
def generate_voice(req: GenerateRequest):
    text = speakable(req.text)
    if not text:
        raise HTTPException(400, "nothing to say after removing markdown and emoji")
    samples, sr = kokoro.create(text, voice=req.voice, speed=req.speed, lang=req.lang)
    buffer = io.BytesIO()
    sf.write(buffer, samples, sr, format="WAV")
    return Response(content=buffer.getvalue(), media_type="audio/wav")


@app.post("/stream")
async def stream_voice(req: GenerateRequest):
    """Raw 16-bit LE mono PCM at 24 kHz, sent as each chunk is generated."""
    text = speakable(req.text)
    if not text:
        raise HTTPException(400, "nothing to say after removing markdown and emoji")

    async def pcm():
        async for samples, _ in kokoro.create_stream(text, voice=req.voice, speed=req.speed, lang=req.lang):
            yield (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()

    return StreamingResponse(pcm(), media_type="audio/pcm", headers={"X-Sample-Rate": "24000"})
