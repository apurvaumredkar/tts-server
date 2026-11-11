# Build context: tts-server/  (docker build -f phonon/Dockerfile .)
FROM ghcr.io/gradium-ai/ptts-openai-server:0.7.0

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir fastapi uvicorn httpx
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY common/ /app/common/
COPY phonon/main.py phonon/entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

USER phonon
EXPOSE 8002
ENTRYPOINT ["/app/entrypoint.sh"]
