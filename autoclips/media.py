from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse
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
    if p.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("Arquivo original ultrapassa limite de 180 MB deste worker")
    os.replace(p, destination)  # Same mounted volume; avoid doubling disk usage.
    return destination


YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_SOURCE_SECONDS = 35 * 60
MAX_SOURCE_BYTES = 180 * 1024 * 1024  # 500 MB Railway volume also holds intermediates.


def _youtube_id(url: str) -> str | None:
    try:
        u = urlparse(url)
        if u.scheme != "https" or u.port not in (None, 443) or u.username or u.password or u.fragment:
            return None
        host = (u.hostname or "").lower()
        query = parse_qs(u.query, keep_blank_values=True)
        if "list" in query or "index" in query or "playlist" in query:
            return None
        if host == "youtu.be":
            candidate = u.path.strip("/") if u.path.count("/") == 1 else ""
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if u.path == "/watch":
                candidate = query.get("v", [""])[0] if len(query.get("v", [])) == 1 else ""
            elif u.path.startswith("/shorts/") and u.path.count("/") == 2:
                candidate = u.path.split("/")[2]
            else:
                return None
        else:
            return None
        return candidate if YOUTUBE_ID.fullmatch(candidate) else None
    except (ValueError, TypeError):
        return None


def is_youtube_link(url: str) -> bool:
    return _youtube_id(url) is not None


def import_youtube_approved(url: str, project_id: str, owner_authorized: bool) -> Path:
    """Download a single approved video using the official yt-dlp extraction API.

    Requires owner confirmation AND explicit deployment opt-in. No cookies,
    credentials, private content, playlist or DRM bypass is attempted. A
    direct authorized upload is the fallback when the source cannot be fetched.
    """
    video_id = _youtube_id(url)
    if not video_id:
        raise ValueError("Envie URL HTTPS de um único vídeo do YouTube (11 caracteres)")
    if not (owner_authorized and youtube_import_allowed()):
        raise PermissionError("A importação está desabilitada: confirme direitos e ALLOW_YOUTUBE_IMPORT=true")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", project_id):
        raise ValueError("ID de projeto inválido")
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp não instalado no worker; verifique a imagem Docker") from exc

    folder = (home() / "projects" / project_id).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    # A temporary subdirectory protects against returning partial files.
    temp_dir = folder / "_downloading"
    temp_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "outtmpl": str(temp_dir / "source.%(ext)s"),
        "format": "bv*[height<=1080][filesize_approx<180M]+ba/b[height<=1080]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 25,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 2,
        "max_filesize": MAX_SOURCE_BYTES,
        "js_runtimes": {"node": {"path": os.environ.get("YT_DLP_NODE_PATH", "/usr/local/bin/node")}},
        "ignoreerrors": False,
        "nooverwrites": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    canonical_url = "https://www.youtube.com/watch?v=" + video_id
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(canonical_url, download=False)
            if not info or info.get("_type", "video") != "video":
                raise ValueError("A URL não aponta para um único vídeo público")
            duration = info.get("duration")
            if not isinstance(duration, (int, float)) or duration <= 0 or duration > MAX_SOURCE_SECONDS:
                raise ValueError("Duração da fonte inválida ou maior que 35 minutos")
            filesize = info.get("filesize") or info.get("filesize_approx")
            if isinstance(filesize, (int, float)) and filesize > MAX_SOURCE_BYTES:
                raise ValueError("Arquivo maior que limite do worker de 180 MB")
            downloader.download([canonical_url])
        candidates = sorted((p for p in temp_dir.iterdir() if p.suffix.lower() in VALID_EXT and p.is_file()), key=lambda p: p.name)
        if len(candidates) != 1 or candidates[0].stat().st_size == 0:
            raise RuntimeError("Não foi possível gerar um único arquivo de vídeo completo")
        if candidates[0].stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Arquivo excedeu limite local de 180 MB")
        target = folder / ("source" + candidates[0].suffix.lower())
        os.replace(candidates[0], target)
        return target
    except (ValueError, PermissionError):
        raise
    except Exception as exc:
        raise RuntimeError("Falha ao importar o vídeo autorizado: " + str(exc) + ". Se o YouTube limitar a origem, envie o MP4 original pela API segura de upload.") from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


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


def import_hosted_approved(url: str, project_id: str, owner_authorized: bool) -> Path:
    """Import a video from a trusted HTTPS media host when YouTube challenges cloud IPs.

    The URL is never logged. No redirects, cookies, private IPs or arbitrary
    URLs are allowed. The owner must authorize the import.
    """
    import urllib.request
    if not owner_authorized:
        raise PermissionError('É necessária autorização para importar a mídia')
    u = urlparse(url)
    if (u.scheme != 'https' or u.hostname != 'storage.googleapis.com'
            or u.port not in (None, 443) or u.username or u.password or not u.path.endswith('.mp4')):
        raise ValueError('URL HTTPS de origem autorizada inválida')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', project_id):
        raise ValueError('ID do projeto inválido')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError('Redirecionamento não autorizado')

    folder = home() / 'projects' / project_id
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / 'source.mp4.part'
    final = folder / 'source.mp4'
    try:
        opener = urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(url, headers={'User-Agent': 'AutoClipsAI/0.8'})
        with opener.open(request, timeout=45) as response:
            if getattr(response, 'status', 200) != 200:
                raise ValueError('A origem de vídeo não retornou HTTP 200')
            size = response.headers.get('Content-Length')
            if size and int(size) > MAX_SOURCE_BYTES:
                raise ValueError('Arquivo maior que limite de tamanho do worker')
            mime = response.headers.get('Content-Type', '').split(';', 1)[0].lower()
            if mime not in ('video/mp4', 'application/octet-stream', ''):
                raise ValueError('A origem não retornou um MP4')
            count = 0
            with tmp.open('wb') as fd:
                while True:
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > MAX_SOURCE_BYTES:
                        raise ValueError('Arquivo maior que limite de tamanho do worker')
                    fd.write(chunk)
        if count < 16:
            raise ValueError('Arquivo de vídeo vazio ou incompleto')
        os.replace(tmp, final)
        return final
    finally:
        tmp.unlink(missing_ok=True)
