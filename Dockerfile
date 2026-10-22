FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860 \
    CORTES_OPEN_BROWSER=false \
    CORTES_CACHE_DIR=/cache \
    GRADIO_TEMP_DIR=/uploads \
    HF_HOME=/home/app/.cache/huggingface \
    GRADIO_ANALYTICS_ENABLED=false

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/saida /app/videos_do_drive /entrada /cache /uploads /home/app/.cache \
    && chown -R app:app /app /cache /uploads /home/app/.cache

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py cli.py visual.py ./
COPY cortes/ ./cortes/
COPY tests/ ./tests/

USER app
EXPOSE 7860
CMD ["python", "app.py"]
