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
MAX_SOURCE_SECONDS = 4 * 60 * 60  # podcasts longos: selecionar qualidade menor automaticamente
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


def _safe_pot_provider() -> str | None:
    """Use only the fixed Railway internal provider; never allow user-supplied URLs."""
    url = os.getenv("AUTOCLIPS_POT_PROVIDER_URL", "").strip()
    if not url:
        return None
    p = urlparse(url)
    if (p.scheme != "http" or p.hostname != "autoclips-pot-provider.railway.internal"
            or p.port != 4416 or p.username or p.password or p.path not in ("", "/")
            or p.query or p.fragment):
        raise RuntimeError("Configuração do provedor de tokens inválida")
    return url


def _source_format(duration: float) -> str:
    """Select quality to keep long originals inside our 180 MiB worker volume.

    Filters prioritize muxed H.264+AAC streams; estimated sizes are not guaranteed.
    Progress hooks enforce an additional hard cap while downloading.
    """
    if duration > 75*60:
        height = 360
    elif duration > 35*60:
        height = 480
    else:
        height = 720
    # Unknown filesize ('?') still permitted; real download bytes remain capped.
    return (
        f"b[height<=?{height}][filesize<?150M]/"
        f"b[height<=?{height}][filesize_approx<?150M]/"
        f"bv*[height<=?{height}][filesize<?135M]+ba[filesize<?15M]/"
        f"bv*[height<=?{height}][filesize_approx<?135M]+ba[filesize_approx<?15M]/"
        f"b[height<=?360]/best[height<=?360]"
    )


def _youtube_options(temp_dir: Path, player_client: str, provider: str | None,
                     duration: float = 900.0) -> dict:
    if player_client not in {"mweb", "tv", "web_safari", "web_embedded"}:
        raise ValueError("Cliente de download não autorizado")
    args = {"youtube": {"player_client": [player_client]}}
    if provider:
        args["youtubepot-bgutilhttp"] = {"base_url": [provider]}

    def cap_bytes(progress):
        # Safe even for chunked manifests: abort if the file exceeds our volume budget.
        downloaded = progress.get("downloaded_bytes")
        if isinstance(downloaded, (int, float)) and downloaded > MAX_SOURCE_BYTES:
            raise ValueError("O vídeo excedeu 180 MB; seleção automática de tamanho falhou")

    return {
        "outtmpl": str(temp_dir / "source.%(ext)s"),
        "format": _source_format(duration),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "socket_timeout": 22,
        "retries": 2,
        "fragment_retries": 2,
        "concurrent_fragment_downloads": 2,
        "max_filesize": MAX_SOURCE_BYTES,
        "progress_hooks": [cap_bytes],
        "extractor_args": args,
        "js_runtimes": {"node": {"path": os.environ.get(
            "YT_DLP_NODE_PATH", "/usr/local/bin/node")}},
        "ignoreerrors": False,
        "nooverwrites": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
    }


def import_youtube_approved(url: str, project_id: str, owner_authorized: bool) -> Path:
    """Owner-authorized link-only ingest, with PO tokens and safe client fallback.

    Never touches browser cookies and does not ask the owner for files.
    Server-IP blocking may still prevent some public videos.
    """
    video_id = _youtube_id(url)
    if not video_id:
        raise ValueError("Envie URL HTTPS de um único vídeo do YouTube")
    if not (owner_authorized and youtube_import_allowed()):
        raise PermissionError("Importação não autorizada neste servidor")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", project_id):
        raise ValueError("ID de projeto inválido")
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp não instalado no Railway") from exc

    provider = _safe_pot_provider()
    folder = (home() / "projects" / project_id).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    temp_dir = folder / "_downloading"
    canonical_url = "https://www.youtube.com/watch?v=" + video_id
    errors = []
    # mweb with official yt-dlp plugin's external PO-token provider first;
    # alternative clients handle videos that do not work with mweb.
    for client in ("mweb", "tv", "web_safari", "web_embedded"):
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        opts = _youtube_options(temp_dir, client, provider)
        try:
            with yt_dlp.YoutubeDL(opts) as downloader:
                info = downloader.extract_info(canonical_url, download=False)
                if not info or info.get("_type", "video") != "video":
                    raise RuntimeError("Vídeo indisponível para importação")
                duration = info.get("duration")
                if not isinstance(duration, (int, float)) or duration <= 0:
                    raise RuntimeError("Não foi possível obter a duração do vídeo")
                if duration > MAX_SOURCE_SECONDS:
                    raise ValueError("Vídeo maior que 4 horas; análise em partes necessária")
                if hasattr(downloader, "params"):
                    downloader.params["format"] = _source_format(float(duration))
                # Allow the downloader to pick an economical format itself,
                # avoiding the original's 1GB+ best-quality representation.
                filesize = info.get("filesize") or info.get("filesize_approx")
                if (isinstance(filesize, (int, float)) and filesize > MAX_SOURCE_BYTES
                        and not info.get("formats")):
                    raise RuntimeError("Nenhuma versão menor do vídeo disponível")
                rc = downloader.download([canonical_url])
                if rc != 0:
                    raise RuntimeError("Download não finalizado")
            files = sorted(p for p in temp_dir.iterdir()
                           if p.suffix.lower() in VALID_EXT and p.is_file())
            if len(files) != 1 or files[0].stat().st_size == 0:
                raise RuntimeError("MP4 final ausente após download")
            if files[0].stat().st_size > MAX_SOURCE_BYTES:
                raise RuntimeError("Fonte acima do limite de 180 MB")
            target = folder / ("source" + files[0].suffix.lower())
            os.replace(files[0], target)
            print("AUTOCLIPS_SOURCE_IMPORTED", video_id, client,
                  "bytes", target.stat().st_size, flush=True)
            return target
        except (PermissionError, ValueError):
            raise
        except Exception as exc:
            # Log only client names and exception types; never token URLs.
            print("AUTOCLIPS_SOURCE_STRATEGY_FAILED", video_id, client,
                  type(exc).__name__, flush=True)
            errors.append((client, type(exc).__name__))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    raise RuntimeError(
        "Download do YouTube bloqueado mesmo após tentar provedores de token "
        "e clientes alternativos. Estratégias: " +
        ", ".join(name for name, _ in errors) + "."
    )


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
