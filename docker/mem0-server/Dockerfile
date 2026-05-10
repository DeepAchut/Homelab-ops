FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    mem0ai==0.1.118 \
    ollama \
    fastapi==0.136.1 \
    uvicorn==0.34.3 \
    pyyaml==6.0.2 \
    psycopg2-binary==2.9.10

COPY main.py /app/main.py

ENV MEM0_CONFIG_PATH=/app/config/config.yaml
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
