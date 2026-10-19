from __future__ import annotations
import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import database as db
from .media import import_local, import_youtube_approved, import_hosted_approved, is_youtube_link, probe
from .ranking import suggest
from .renderer import render
from .split_renderer import render_split, validate_window, clamp_focal
from .contextual_image import fetch_public_domain_image, topic_terms
from .context import contextual_window
from .settings import home
from .transcript import transcribe, save_transcript, load_transcript
from .youtube import channel, upload, validate_schedule

# Motor de tarefas local: permanece ativo apenas enquanto o processo estiver aberto.
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="autoclips")
INIT_LOCK = threading.Lock()
RESTORE_LOCK = threading.Lock()
INITIALIZED = set()


def init() -> None:
    # Multiple workspaces can be used by tests and local tooling in one process.
    root = str(home())
    with INIT_LOCK:
        if root not in INITIALIZED:
            db.init_db()
            INITIALIZED.add(root)


def _work(job_id: str, fn, *args) -> None:
    db.update("jobs", job_id, status="running", updated=db.now())
    try:
        result = fn(*args)
        db.update("jobs", job_id, status="completed", result=json.dumps(result, ensure_ascii=False), updated=db.now())
    except Exception as exc:
        db.update("jobs", job_id, status="failed", error=str(exc), updated=db.now())


def _submit(kind: str, target_id: str, fn, *args) -> str:
    init()
    job_id = db.newid("job")
    with db.conn() as c:
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (job_id, kind, target_id, "queued", None, None, db.now(), db.now()))
    POOL.submit(_work, job_id, fn, *args)
    return job_id


def new_project(source: str, source_kind: str = "file", authorized: bool = False,
                auto_transcribe: bool = True) -> dict:
    """Cria projeto e importa, opcionalmente transcreve. Não posta nada."""
    init()
    if source_kind not in {"file", "youtube", "hosted"}:
        raise ValueError("source_kind deve ser file, youtube ou hosted")
    if source_kind == "youtube" and not is_youtube_link(source):
        raise ValueError("URL do YouTube inválida")
    if source_kind in {"youtube", "hosted"} and not authorized:
        raise PermissionError("Confirme direitos e autorização de importação do vídeo")
    id_ = db.newid("prj")
    with db.conn() as c:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (id_, source_kind, source, Path(source).name if source_kind == "file" else "Vídeo autorizado",
                   None, None, None, "queued", None, db.now()))
    job = _submit("ingest", id_, _ingest, id_, source, source_kind, authorized, auto_transcribe)
    return {"project_id": id_, "job_id": job, "status": "queued"}


def _ingest(id_: str, source: str, source_kind: str, authorized: bool, auto_transcribe: bool) -> dict:
    db.update("projects", id_, status="importing")
    try:
        media = (import_local(source, id_) if source_kind == "file"
                 else import_hosted_approved(source, id_, authorized) if source_kind == "hosted"
                 else import_youtube_approved(source, id_, authorized))
        info = probe(media)
        db.update("projects", id_, media=str(media), duration=info["duration"], status="imported")
        if not auto_transcribe:
            return {"media": str(media), **info, "next": "transcribe_project"}
        return _transcribe(id_, None)
    except Exception as exc:
        db.update("projects", id_, status="failed", error=str(exc))
        raise


def _transcribe(id_: str, srt_filename: str | None) -> dict:
    project = db.one("projects", id_)
    if not project.get("media"):
        raise ValueError("A importação ainda não terminou")
    db.update("projects", id_, status="transcribing")
    try:
        srt_path = None
        if srt_filename:
            p = (home() / "imports" / srt_filename).resolve()
            if p.parent != (home() / "imports").resolve() or p.suffix.lower() != ".srt" or not p.is_file():
                raise ValueError("SRT deve estar em storage/imports")
            srt_path = p
        result = transcribe(Path(project["media"]), srt_path=srt_path,
                            model_name=os.getenv("WHISPER_MODEL", "small"),
                            device=os.getenv("WHISPER_DEVICE", "cpu"),
                            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
        path = save_transcript(id_, result, home())
        db.update("projects", id_, transcript=str(path), status="ready", error=None)
        return {"project_id": id_, "transcript": str(path), "language": result["language"],
                "segments": len(result["segments"]), "words": len(result["words"]),
                "next": "read_transcript e suggest_clips"}
    except Exception as exc:
        db.update("projects", id_, status="transcription_failed", error=str(exc))
        raise


def start_transcription(project_id: str, srt_filename: str | None = None) -> dict:
    init()
    db.one("projects", project_id)
    return {"job_id": _submit("transcribe", project_id, _transcribe, project_id, srt_filename)}


def read_transcript(project_id: str, offset: int = 0, limit: int = 60) -> dict:
    init()
    p = db.one("projects", project_id)
    if not p["transcript"]:
        raise ValueError("Transcrição ainda não disponível")
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset >= 0 e 1 <= limit <= 200")
    data = load_transcript(p["transcript"])
    segs = data["segments"]
    return {"project_id": project_id, "language": data["language"], "total": len(segs),
            "offset": offset, "next_offset": offset + limit if offset + limit < len(segs) else None,
            "segments": segs[offset:offset + limit]}


def suggest_clips(project_id: str, count: int = 5, min_seconds: int = 25,
                  max_seconds: int = 60) -> dict:
    init()
    p = db.one("projects", project_id)
    if not p["transcript"]:
        raise ValueError("Primeiro transcreva o projeto")
    data = load_transcript(p["transcript"])
    return {"project_id": project_id, "method": "heuristic_requires_editorial_review",
            "suggestions": suggest(data["segments"], p["duration"], count, min_seconds, max_seconds)}


def start_render(project_id: str, start: float, end: float, style: str = "viral") -> dict:
    init()
    p = db.one("projects", project_id)
    if not p.get("transcript"):
        raise ValueError("Transcreva o vídeo antes de gerar legendas")
    if not p.get("duration") or start < 0 or end <= start or end > p["duration"] + .1 or end-start > 180:
        raise ValueError("Intervalo inválido ou duração maior que 180s")
    if style not in {"viral", "clean", "bold"}:
        raise ValueError("Estilo inválido")
    clip_id = db.newid("clip")
    with db.conn() as c:
        c.execute("INSERT INTO clips (id, project_id, start, end, style, path, status, error, created) VALUES (?,?,?,?,?,?,?,?,?)",
                  (clip_id, project_id, start, end, style, None, "queued", None, db.now()))
    job_id = _submit("render", clip_id, _render, clip_id)
    return {"clip_id": clip_id, "job_id": job_id, "status": "queued"}


def _media_for_render(project: dict) -> str:
    """Reload a checksummed source from private S3 only when needed for an edit."""
    source = Path(project["media"])
    if source.is_file():
        return str(source)
    from .source_archive import restore_source
    with RESTORE_LOCK:
        return str(restore_source(project["id"], source))


def _render(clip_id: str) -> dict:
    clip = db.one("clips", clip_id)
    project = db.one("projects", clip["project_id"])
    db.update("clips", clip_id, status="rendering")
    try:
        transcript = load_transcript(project["transcript"])
        export = home() / "exports" / f"{clip_id}.mp4"
        result = render(_media_for_render(project), transcript["words"], clip["start"], clip["end"], export, clip["style"])
        db.update("clips", clip_id, path=str(export), status="ready")
        return {"clip_id": clip_id, **result}
    except Exception as exc:
        db.update("clips", clip_id, status="failed", error=str(exc))
        raise



def plan_context_clip(project_id: str, anchor_start: float, anchor_end: float,
                      min_seconds: float = 35, max_seconds: float = 90) -> dict:
    """Extend a short anchor with the question/setup and a meaningful conclusion."""
    init()
    project = db.one("projects", project_id)
    if not project.get("transcript"):
        raise ValueError("Transcrição com timestamps obrigatória")
    result = contextual_window(load_transcript(project["transcript"])["segments"],
                               anchor_start, anchor_end, min_seconds, max_seconds)
    if result["end"] > float(project.get("duration") or 0) + .1:
        raise ValueError("Janela ultrapassa duração da fonte")
    return {"project_id": project_id, **result}


def start_render_split(project_id: str, start: float, end: float,
                       image_filename: str | None = None, focal_x: float = .5,
                       hook_white: str = "", hook_red: str = "") -> dict:
    """Queue top-video/bottom-image Shorts up to 180 seconds.
    Still images must be uploaded to storage/imports; no arbitrary URL fetch.
    """
    init()
    project = db.one("projects", project_id)
    validate_window(start, end)
    if not project.get("transcript") or not project.get("media"):
        raise ValueError("Importe e transcreva o vídeo primeiro")
    if end > (project.get("duration") or 0) + .1:
        raise ValueError("Trecho termina depois do vídeo")
    focal_x = clamp_focal(focal_x)
    if image_filename is not None:
        importdir = (home() / "imports").resolve()
        path = (importdir / image_filename).resolve()
        if path.parent != importdir or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} or not path.is_file():
            raise ValueError("Imagem contextual deve ser JPG/PNG/WEBP em storage/imports")
        image_file = str(path)
    else:
        image_file = None
    clip_id = db.newid("clip")
    with db.conn() as c:
        c.execute("INSERT INTO clips (id,project_id,start,end,style,path,status,error,created) VALUES (?,?,?,?,?,?,?,?,?)",
                  (clip_id,project_id,start,end,"split",None,"queued",None,db.now()))
    job_id = _submit("render_split",clip_id,_render_split,clip_id,image_file,focal_x,hook_white,hook_red)
    return {"clip_id":clip_id,"job_id":job_id,"status":"queued","layout":"split"}


def _render_split(clip_id: str, image_file: str | None, focal_x: float,
                  hook_white: str = "", hook_red: str = "") -> dict:
    clip = db.one("clips",clip_id)
    project = db.one("projects",clip["project_id"])
    db.update("clips",clip_id,status="rendering")
    try:
        transcript = load_transcript(project["transcript"])
        target = home() / "exports" / f"{clip_id}.mp4"
        source = _media_for_render(project)
        # An original frame is allowed only as a clearly labelled preview.
        # Auto-approval requires a separate, topic-matched, licensed photo.
        photo = None
        photo_credit = ""
        if image_file is None:
            title = str(project.get("name") or "")
            spoken = " ".join(str(seg.get("text", "")) for seg in transcript["segments"]
                            if seg["end"] > clip["start"] and seg["start"] < clip["end"]).lower()
            terms = topic_terms(title)
            if terms and any(term in spoken for term in terms):
                photo = fetch_public_domain_image(title, target.with_name(clip_id + "_related"))
        selected_image = image_file or (photo["path"] if photo else None)
        if photo:
            photo_credit = photo["credit"]
        outcome = render_split(source=source,image=selected_image,
                               words=transcript["words"],start=clip["start"],end=clip["end"],
                               output=target,focal_x=focal_x,size=(540,960),credit=photo_credit,
                               hook_white=hook_white or None,hook_red=hook_red or None)
        image_kind = ("owner_provided" if image_file else
                      "wikimedia_public_domain" if photo else "source_frame_preview_only")
        quality = {
            "language": transcript.get("language"),
            "image_mode": image_kind,
            "image_credit": photo_credit,
            "image_title": photo["title"] if photo else "",
            "caption_events": outcome["caption_events"],
            "layout": outcome["layout"],
            "auto_publish_ready": (transcript.get("language") == "pt" and
                                   outcome["caption_events"] > 0 and
                                   image_kind in {"wikimedia_public_domain", "owner_provided"})
        }
        # Do not label an ordinary extracted frame as context photography.
        target.with_suffix(".qa.json").write_text(
            json.dumps(quality, ensure_ascii=False), encoding="utf-8")
        db.update("clips",clip_id,path=str(target),status="ready")
        return {"clip_id":clip_id,**outcome,"quality":quality}
    except Exception as exc:
        db.update("clips",clip_id,status="failed",error=str(exc))
        raise

def prepare_upload(clip_id: str, title: str, description: str, privacy: str,
                   made_for_kids: bool, publish_at: str | None = None) -> dict:
    init()
    c = db.one("clips", clip_id)
    if c["status"] != "ready" or not c.get("path"):
        raise ValueError("Esse clip não está renderizado")
    if c.get("uploaded_url"):
        raise ValueError("Esse clip já foi enviado. Consulte list_clips para o link.")
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("Privacidade deve ser private, unlisted ou public")
    if not (1 <= len(title) <= 100) or len(description) > 5000:
        raise ValueError("Título entre 1 e 100 caracteres; descrição até 5000")
    publish_at = validate_schedule(publish_at, privacy)
    ch = channel()
    reservation = db.reserve_approval(clip_id, title, description, privacy, made_for_kids, publish_at, ch["id"])
    return {"clip_id": clip_id, "file": c["path"], "channel": ch,
            "title": title, "description": description, "privacy": privacy,
            "made_for_kids": made_for_kids, "publish_at": publish_at,
            "approval": reservation,
            "requires_explicit_user_approval": True,
            "instruction": "Mostre canal, vídeo, título, privacidade e programação. Peça aprovação expressa antes de chamar confirm_upload."}


def confirm_upload(approval_token: str) -> dict:
    init()
    approved = db.consume_approval(approval_token)
    c = db.one("clips", approved["clip_id"])
    if c["status"] != "ready" or c.get("uploaded_url"):
        raise ValueError("Clip indisponível ou já enviado")
    job_id = _submit("upload", c["id"], _upload, approved)
    return {"job_id": job_id, "clip_id": c["id"], "status": "queued"}


def _upload(approval: dict) -> dict:
    clip_id = approval["clip_id"]
    c = db.one("clips", clip_id)
    url = upload(c["path"], approval["title"], approval["description"], approval["privacy"],
                 bool(approval["made_for_kids"]), approval["channel_id"], approval["publish_at"])
    db.update("clips", clip_id, uploaded_url=url)
    return {"clip_id": clip_id, "youtube_url": url, "privacy_requested": approval["privacy"]}


def job_status(job_id: str) -> dict:
    init()
    j = db.one("jobs", job_id)
    if j["result"]:
        j["result"] = json.loads(j["result"])
    return j


def list_projects() -> list[dict]:
    init()
    return db.rows("projects")


def list_clips(project_id: str) -> list[dict]:
    init()
    db.one("projects", project_id)
    return db.rows("clips", "project_id", project_id)
