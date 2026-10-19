FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTOCLIPS_HOME=/data \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    ALLOW_YOUTUBE_IMPORT=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY autoclips ./autoclips
COPY server.py cloud_server.py ./
RUN pip install --no-cache-dir .
RUN mkdir -p /data && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin autoclips && chown -R autoclips:autoclips /data
USER autoclips
CMD ["sh", "-c", "exec uvicorn cloud_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
