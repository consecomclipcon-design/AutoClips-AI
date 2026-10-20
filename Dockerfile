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
    ffmpeg fonts-dejavu-core fonts-lato ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY autoclips ./autoclips
COPY server.py cloud_server.py dashboard.html ./
RUN pip install --no-cache-dir ".[youtube-import]" && node --version && python -c "import yt_dlp; print(yt_dlp.version.__version__)"
# Fail the deployment early if editorial/image modules have syntax errors
# or the split layout regresses to hiding the central caption band.
RUN python -m compileall -q autoclips && python -c "from autoclips.split_renderer import build_filters; from autoclips.contextual_image import topic_terms; from autoclips.editorial import require_spoken_portuguese; assert 'overlay=0:546:shortest=1' in build_filters('caption.ass'); assert topic_terms('Ramon Dino')[:2] == ['ramon','dino']"
# Validate the immutable hook at build time rather than risking a bad production render.
RUN python -c "from autoclips.static_hook import generate_static_hook; from autoclips.split_renderer import write_static_hook; from pathlib import Path; import tempfile; seg=[{'start':0,'end':6,'text':'Qual suplemento tomar? Vou explicar agora.'},{'start':6,'end':12,'text':'Tem creatina e whey para considerar.'}]; hook=generate_static_hook('Qual suplemento tomar?',seg,0,12); assert hook['top']=='QUAL SUPLEMENTO'; assert hook['bottom']=='VOCÊ DEVE TOMAR?'; f=Path(tempfile.gettempdir())/'autoclips_hook_build.ass'; assert write_static_hook(f,0,12,hook['top'],hook['bottom'])==2; data=f.read_text(); assert data.count('Dialogue:')==3 and '0:00:12.00' in data"
RUN mkdir -p /data && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin autoclips && chown -R autoclips:autoclips /data
COPY docker-entrypoint.sh /usr/local/bin/autoclips-entrypoint.sh
RUN chmod 0755 /usr/local/bin/autoclips-entrypoint.sh
USER root
ENTRYPOINT ["/usr/local/bin/autoclips-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn cloud_server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
