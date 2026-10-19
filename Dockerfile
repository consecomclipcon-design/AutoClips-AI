FROM node:22-bookworm-slim AS node

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTOCLIPS_HOME=/data \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    ALLOW_YOUTUBE_IMPORT=false
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV YT_DLP_NODE_PATH=/usr/local/bin/node
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-dejavu-core ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY autoclips ./autoclips
COPY server.py cloud_server.py dashboard.html ./
RUN pip install --no-cache-dir ".[youtube-import]" && node --version && python -c "import yt_dlp; print(yt_dlp.version.__version__)"
RUN mkdir -p /data && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin autoclips && chown -R autoclips:autoclips /data
COPY docker-entrypoint.sh /usr/local/bin/autoclips-entrypoint.sh
RUN chmod 0755 /usr/local/bin/autoclips-entrypoint.sh
USER root
ENTRYPOINT ["/usr/local/bin/autoclips-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn cloud_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
