# mem0 API server on mem0ai 2.x (test/migration image — build as a :2x tag,
# NOT :latest, until cutover). See docker/mem0-server/ for the current 0.1.118 prod build.
FROM python:3.12-slim

WORKDIR /app

# ollama pinned to a build that still exposes the `think` kwarg on Client.chat
# (needed for the qwen3 think=False patch). mem0ai 2.x does NOT hard-depend on
# ollama, so it must be installed explicitly.
RUN pip install --no-cache-dir \
    mem0ai==2.0.15 \
    ollama==0.6.2 \
    fastapi==0.136.1 \
    uvicorn==0.34.3 \
    pyyaml==6.0.2 \
    psycopg2-binary==2.9.10

COPY main.py /app/main.py

ENV MEM0_CONFIG_PATH=/app/config/config.yaml
ENV MEM0_TELEMETRY=false
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
