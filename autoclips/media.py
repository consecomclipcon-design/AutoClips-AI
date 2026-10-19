from __future__ import annotations
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from .settings import home, youtube_import_allowed

VALID_EXT = {".mp4", ".mkv", ".mov", ".webm"}


def import_local(filename: str, project_id: str) -> Path:
    p = (home() / "imports" / filename).resolve()
    if p.parent != (home() / "imports").resolve():
        raise ValueError("O arquivo precisa estar diretamente na pasta storage/imports")
    if not p.is_file() or p.suffix.lower() not in VALID_EXT:
        raise ValueError("Arquivo não encontrado ou formato inválido (MP4, MOV, MKV, WEBM)")
    destination = home() / "projects" / project_id / ("source" + p.suffix.lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, destination)
    return destination


def is_youtube_link(url: str) -> bool:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        return u.scheme == "https" and host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"} and bool(u.path.strip("/"))
    except ValueError:
        return False


def import_youtube_approved(url: str, project_id: str, owner_authorized: bool) -> Path:
    if not is_youtube_link(url):
        raise ValueError("Envie uma URL HTTPS válida do YouTube")
    if not (owner_authorized and youtube_import_allowed()):
        raise PermissionError("Download desabilitado. Use arquivo original, ou obtenha autorização prévia por escrito do YouTube e do titular antes de habilitar ALLOW_YOUTUBE_IMPORT.")
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("Instale o extra opcional: pip install -e '.[youtube-import]'") from exc
    folder = home() / "projects" / project_id
    folder.mkdir(parents=True, exist_ok=True)
    opts = {"outtmpl": str(folder / "source.%(ext)s"),
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "merge_output_format": "mp4", "noplaylist": True,
            "quiet": True, "no_warnings": True,
            "max_filesize": 3 * 1024 * 1024 * 1024}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    candidates = [f for f in folder.glob("source.*") if f.suffix.lower() in VALID_EXT]
    if not candidates:
        raise RuntimeError("Não foi possível importar o vídeo")
    return candidates[0]


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=width,height,codec_type", "-of", "json", str(path)],
             check=True, text=True, capture_output=True)
    data = json.loads(result.stdout)
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise ValueError("O arquivo não possui faixa de vídeo")
    duration = float(data["format"]["duration"])
    if duration <= 0:
        raise ValueError("Duração do vídeo inválida")
    return {"duration": duration, "width": streams[0].get("width"), "height": streams[0].get("height")}
