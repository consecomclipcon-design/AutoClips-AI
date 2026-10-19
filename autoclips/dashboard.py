"""Private owner dashboard: TikTok-like review, bulk ingest, feedback and approval.

The browser uses a short-lived, signed HttpOnly session cookie. Existing MCP
Bearer auth remains independent. Every state-changing request requires same-
origin fetch, a custom CSRF header and an authenticated cookie.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from . import database as db
from . import pipeline
from .editorial import select_contextual_portuguese_clips
from .transcript import load_transcript
from .publish_queue import create_tables as init_publications, enqueue_publication, daily_status, publish_next
from .settings import home

ORIGIN = "https://autoclips-worker-production.up.railway.app"
SESSION_NAME = "ac_dashboard"
SESSION_SECONDS = 5 * 24 * 3600
_WORKER_STARTED = False
_LOGINS: dict[str, list[float]] = {}


def _db_init():
    init_publications()
    with db.conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS dashboard_sources(
          id TEXT PRIMARY KEY,
          link TEXT NOT NULL,
          source_kind TEXT NOT NULL,
          status TEXT NOT NULL,
          project_id TEXT,
          job_id TEXT,
          error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dashboard_renders(
          clip_id TEXT PRIMARY KEY, source_id TEXT, job_id TEXT,
          status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dashboard_feedback(
          id TEXT PRIMARY KEY, clip_id TEXT NOT NULL,
          decision TEXT NOT NULL, comment TEXT,
          created_at TEXT NOT NULL, remake_clip_id TEXT
        );
        CREATE TABLE IF NOT EXISTS dashboard_quality_retests(
          source_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
          status TEXT NOT NULL, clip_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dashboard_image_repairs(
          source_id TEXT PRIMARY KEY, old_clip_id TEXT NOT NULL,
          new_clip_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        # Retry a bot-blocked link once for each materially new download
        # strategy. Normal UI reads and process restarts never burn retries.
        retry_revision = "dualstack-pot-v1"
        columns = {col["name"] for col in c.execute("PRAGMA table_info(dashboard_sources)")}
        if "auto_retry_count" not in columns:
            c.execute("ALTER TABLE dashboard_sources ADD COLUMN auto_retry_count INTEGER NOT NULL DEFAULT 0")
        if "retry_revision" not in columns:
            c.execute("ALTER TABLE dashboard_sources ADD COLUMN retry_revision TEXT NOT NULL DEFAULT ''")
        if "title" not in columns:
            c.execute("ALTER TABLE dashboard_sources ADD COLUMN title TEXT")
        if "original_video_id" not in columns:
            c.execute("ALTER TABLE dashboard_sources ADD COLUMN original_video_id TEXT")
        # Resume a vidIQ import interrupted by the model-cache migration.
        # Do not requeue successful jobs or continuously retry failed media.
        r = c.execute("""UPDATE dashboard_sources SET status='queued',
                         job_id=NULL,project_id=NULL,error=NULL,
                         retry_revision='vidiq-cache-v1',updated_at=?
                         WHERE source_kind='hosted' AND status='failed'
                         AND retry_revision<>'vidiq-cache-v1'
                         AND (lower(coalesce(error,'')) LIKE '%permission denied%'
                           OR lower(coalesce(error,'')) LIKE '%interrupted%'
                           OR lower(coalesce(error,'')) LIKE '%reiniciado%')""",(db.now(),))
        if r.rowcount:
            print("AUTOCLIPS_VIDIQ_CACHE_RECOVERY_ENQUEUED",r.rowcount,flush=True)

        # One-time NASA/JPL public-domain validation requested by the owner.
        # Never logs signed media URL and never reposts on restart.
        nasa_url = os.getenv("AUTOCLIPS_PRIVATE_VALIDATION_MEDIA_URL", "")
        if os.getenv("AUTOCLIPS_PRIVATE_VALIDATION_ENABLED") == "true" and nasa_url:
            parsed_test = urlparse(nasa_url)
            if (parsed_test.scheme == "https" and
                    parsed_test.hostname == "storage.googleapis.com" and
                    parsed_test.path.endswith(".mp4") and
                    not parsed_test.username and not parsed_test.password):
                c.execute("""INSERT OR IGNORE INTO dashboard_sources
                    (id,link,source_kind,status,created_at,updated_at,title,original_video_id)
                    VALUES (? ,? ,'hosted','queued',?,?,?,?)""",
                    ("src_nasa_validation_20261019", nasa_url,
                     "2026-01-01T00:00:00+00:00", db.now(),
                     "NASA JPL - What Is a Dwarf Planet (teste privado)",
                     "Er5L6cxnRTc"))
            else:
                print("AUTOCLIPS_PRIVATE_VALIDATION_URL_INVALID", flush=True)

        c.execute("""CREATE TABLE IF NOT EXISTS chat_ingest_permissions(
              source_id TEXT PRIMARY KEY,
              original_video_id TEXT NOT NULL,
              private_publish_approved INTEGER NOT NULL DEFAULT 0,
              rights_confirmed INTEGER NOT NULL DEFAULT 0
        )""")
        # Connected ChatGPT agents can submit a single signed media URL via the
        # OAuth-protected Railway variable tool, without touching older batches.
        # Existing source/approval records are never overwritten by a new job.
        raw_chat = os.getenv("AUTOCLIPS_AGENT_CHAT_IMPORT", "")
        if raw_chat:
            try:
                entry = json.loads(raw_chat)
                video_id = entry.get("video_id", "")
                url = entry.get("media_url", "")
                title = entry.get("title", "")
                source_url = entry.get("youtube_url", "")
                parsed = urlparse(url)
                if (not isinstance(entry, dict) or
                        not isinstance(video_id, str) or
                        not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or
                        not isinstance(url, str) or len(url) > 2048 or
                        parsed.scheme != "https" or
                        parsed.hostname != "storage.googleapis.com" or
                        not parsed.path.endswith(".mp4") or
                        parsed.username or parsed.password or
                        not isinstance(title, str) or not 1 <= len(title) <= 160 or
                        source_url != "https://www.youtube.com/watch?v=" + video_id):
                    raise ValueError("invalid_chat_media")
                sid = "src_chat_" + video_id.replace("-", "_")
                c.execute("""INSERT OR IGNORE INTO dashboard_sources
                    (id,link,source_kind,status,created_at,updated_at,
                     title,original_video_id)
                    VALUES (?,?,'hosted','queued',?,?,?,?)""",
                    (sid,url,db.now(),db.now(),title,video_id))
                c.execute("""INSERT OR IGNORE INTO chat_ingest_permissions
                    (source_id,original_video_id,private_publish_approved,rights_confirmed)
                    VALUES (?,?,?,?)""",
                    (sid,video_id,
                     int(entry.get("private_publish_approved") is True),
                     int(entry.get("rights_confirmed") is True)))
            except (ValueError, TypeError, KeyError, AttributeError):
                print("AUTOCLIPS_CHAT_MEDIA_INVALID",flush=True)

        # The signed media URLs are supplied only as PRIVATE Railway variables.
        # Never log them, put them in Git, or expose in a UI response.
        raw_batch = os.getenv("AUTOCLIPS_VIDIQ_REVIEW_BATCH", "")
        if raw_batch:
            try:
                entries = json.loads(raw_batch)
                if not isinstance(entries, list) or len(entries) > 25:
                    raise ValueError("invalid manifest")
                for entry in entries:
                    video_id = str(entry.get("video_id", ""))
                    media_url = str(entry.get("media_url", ""))
                    title = str(entry.get("title", ""))[:160]
                    if not re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                        raise ValueError("invalid video id")
                    parsed = urlparse(media_url)
                    if (not title or parsed.scheme != "https" or
                        parsed.hostname != "storage.googleapis.com" or
                        not parsed.path.endswith(".mp4") or parsed.username or parsed.password):
                        raise ValueError("invalid signed video URL")
                    sid = "src_vidiq_" + video_id.replace("-", "_")
                    c.execute("""INSERT OR IGNORE INTO dashboard_sources
                                 (id,link,source_kind,status,created_at,updated_at,title,original_video_id)
                                 VALUES (?,?,'hosted','queued',?,?,?,?)""",
                              (sid, media_url, db.now(), db.now(), title, video_id))
                # Idempotent across restarts and dashboard polling.
            except (ValueError, TypeError, KeyError) as exc:
                print("AUTOCLIPS_VIDIQ_MANIFEST_INVALID", type(exc).__name__, flush=True)

        retried = c.execute("""UPDATE dashboard_sources
                        SET status='queued',error=NULL,project_id=NULL,job_id=NULL,
                            auto_retry_count=auto_retry_count+1,
                            retry_revision=?,updated_at=?
                        WHERE source_kind='youtube' AND status='failed'
                          AND retry_revision<>?
                          AND (lower(coalesce(error,'')) LIKE '%not a bot%'
                            OR lower(coalesce(error,'')) LIKE '%sign in to confirm%'
                            OR lower(coalesce(error,'')) LIKE '%youtube bloqueou%'
                            OR lower(coalesce(error,'')) LIKE '%download do youtube bloqueado%')
                       """,(retry_revision,db.now(),retry_revision))
        if retried.rowcount:
            print("AUTOCLIPS_RETRY_NEW_STRATEGY",retry_revision,retried.rowcount,flush=True)


def _secret() -> bytes:
    s = os.environ.get("MCP_GATEWAY_TOKEN", "")
    if len(s) < 32:
        raise RuntimeError("Session encryption key missing")
    return s.encode("utf-8")


def _cookie(expiry: int) -> str:
    payload = str(expiry)
    signature = hmac.new(_secret(), ("dashboard-v1:" + payload).encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _valid(request) -> bool:
    value = request.cookies.get(SESSION_NAME, "")
    try:
        expiry, sig = value.split(".", 1)
        if not expiry.isdigit() or int(expiry) <= time.time() or int(expiry) > time.time() + SESSION_SECONDS + 60:
            return False
        expected = _cookie(int(expiry)).split(".", 1)[1]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _auth(request, write=False) -> JSONResponse | None:
    if not _valid(request):
        return JSONResponse({"error": "login_required"}, status_code=401)
    if write:
        if request.headers.get("x-autoclips-action") != "1":
            return JSONResponse({"error": "csrf_header_required"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != ORIGIN:
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
    return None


def _answer(obj, status=200):
    return JSONResponse(obj, status_code=status, headers={"cache-control": "no-store",
        "x-content-type-options": "nosniff", "x-frame-options": "DENY"})


async def app_page(request):
    root = Path(__file__).parent.parent
    path = root / "dashboard.html"
    response = FileResponse(path, media_type="text/html",
                            headers={"cache-control": "no-store", "x-frame-options": "DENY",
                                     "referrer-policy": "no-referrer",
                                     "x-content-type-options": "nosniff"})
    return response


async def login(request):
    try:
        data = await request.json()
        pw = data.get("password", "")
        if not isinstance(pw, str) or len(pw) > 500:
            return _answer({"error": "invalid_password"}, 400)
    except Exception:
        return _answer({"error": "invalid_json"}, 400)
    expected = os.getenv("AUTOCLIPS_DASHBOARD_PASSWORD", "")
    if len(expected) < 16:
        return _answer({"error": "dashboard_not_configured"}, 503)
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    prior = [v for v in _LOGINS.get(ip, []) if now-v < 900]
    if len(prior) >= 8:
        return _answer({"error": "too_many_attempts"}, 429)
    prior.append(now)
    _LOGINS[ip] = prior
    if not hmac.compare_digest(pw.encode(), expected.encode()):
        return _answer({"error": "incorrect_password"}, 401)
    _LOGINS.pop(ip, None)
    resp = _answer({"ok": True, "user": "ClipCon"})
    resp.set_cookie(SESSION_NAME, _cookie(int(time.time())+SESSION_SECONDS),
                    max_age=SESSION_SECONDS, secure=True, httponly=True,
                    samesite="strict", path="/")
    return resp


async def logout(request):
    err = _auth(request, write=True)
    if err: return err
    response = _answer({"ok": True})
    response.delete_cookie(SESSION_NAME,path="/")
    return response


async def session(request):
    return _answer({"loggedIn": _valid(request)})


async def status(request):
    err = _auth(request)
    if err: return err
    _db_init()
    with db.conn() as c:
        statuses = [dict(row) for row in c.execute(
            "SELECT status,count(*) AS count FROM dashboard_sources GROUP BY status")]
    try:
        from .oauth_web import connection_status
        youtube = connection_status()
    except Exception:
        youtube = {"connected": False}
    return _answer({"quota": daily_status(), "sources": statuses, "youtube": youtube})


async def feed(request):
    err = _auth(request)
    if err: return err
    _db_init()
    with db.conn() as c:
        rows = c.execute("""SELECT c.id,c.project_id,c.start,c.end,c.status,
                            c.uploaded_url,c.created,p.name AS project_name,
                            q.status AS publication_status,q.error AS publication_error,
                            q.youtube_url,
                            (SELECT f.decision FROM dashboard_feedback f
                             WHERE f.clip_id=c.id ORDER BY f.created_at DESC LIMIT 1)
                             AS decision,
                            (SELECT f.comment FROM dashboard_feedback f
                             WHERE f.clip_id=c.id ORDER BY f.created_at DESC LIMIT 1)
                             AS feedback
                            FROM clips c LEFT JOIN projects p ON p.id=c.project_id
                            LEFT JOIN dashboard_publishes q ON q.clip_id=c.id
                            WHERE c.path IS NOT NULL AND c.status='ready'
                            ORDER BY c.created DESC LIMIT 120""").fetchall()
    clips = []
    for row in rows:
        clip = dict(row)
        clip["mediaUrl"] = "/api/console/media/" + clip["id"]
        clips.append(clip)
    return _answer({"clips": clips, "quota": daily_status()})


async def media(request):
    err = _auth(request)
    if err: return err
    clip_id = request.path_params["clip_id"]
    if not re.fullmatch(r"clip_[a-zA-Z0-9_]{3,70}", clip_id):
        return _answer({"error": "bad_clip_id"}, 400)
    try:
        clip = db.one("clips",clip_id)
        target = Path(clip.get("path") or "").resolve()
        root = home().resolve()
        if not target.is_file() or not target.is_relative_to(root) or target.suffix.lower() != ".mp4":
            return _answer({"error": "media_not_found"}, 404)
        return FileResponse(target,media_type="video/mp4",
                            headers={"cache-control": "private,max-age=3600",
                                     "x-content-type-options": "nosniff"})
    except (ValueError, OSError):
        return _answer({"error": "media_not_found"}, 404)


def _validate_kind(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if host in {"youtube.com","www.youtube.com","m.youtube.com","youtu.be","www.youtu.be"}:
        return "youtube"
    if host == "storage.googleapis.com" and parsed.path.endswith(".mp4"):
        return "hosted"
    return None


async def add_links(request):
    err = _auth(request,write=True)
    if err: return err
    try:
        payload = await request.body()
        if len(payload) > 30_000: return _answer({"error": "too_large"}, 413)
        data = json.loads(payload)
        links = data.get("links")
        if isinstance(links,str):
            links = [v.strip() for v in links.splitlines() if v.strip()]
        if not isinstance(links,list) or not 1 <= len(links) <= 25:
            return _answer({"error": "provide_1_to_25_links"}, 400)
        if data.get("authorized") is not True:
            return _answer({"error": "source_authorization_required"}, 403)
    except Exception:
        return _answer({"error": "invalid_json"}, 400)
    _db_init()
    response=[]
    with db.conn() as c:
        active=c.execute("""SELECT count(*) FROM dashboard_sources
                            WHERE status IN ('queued','importing','rendering')""").fetchone()[0]
        if active+len(links)>60:
            return _answer({"error": "queue_full_try_later"}, 429)
        for link in links:
            if not isinstance(link,str) or len(link)>2048 or not _validate_kind(link):
                response.append({"link": str(link)[:100], "status": "invalid_link"})
                continue
            sid=db.newid("src")
            c.execute("""INSERT INTO dashboard_sources
                         (id,link,source_kind,status,created_at,updated_at)
                         VALUES (?,?,?,'queued',?,?)""",
                     (sid,link,_validate_kind(link),db.now(),db.now()))
            response.append({"id":sid,"status":"queued"})
    return _answer({"items":response},202)


async def sources(request):
    err = _auth(request)
    if err: return err
    _db_init()
    with db.conn() as c:
        rows=c.execute("""SELECT id,source_kind,status,error,created_at,updated_at,project_id
                          FROM dashboard_sources ORDER BY created_at DESC LIMIT 80""").fetchall()
    return _answer({"sources":[dict(r) for r in rows]})


async def review(request):
    err = _auth(request,write=True)
    if err: return err
    try:
        data = await request.json()
        clip_id = data.get("clip_id")
        decision = data.get("decision")
        comment = data.get("comment", "")
        if not isinstance(clip_id,str) or not re.fullmatch(r"clip_[a-zA-Z0-9_]{3,70}",clip_id):
            return _answer({"error":"clip_id_invalid"},400)
        if decision not in {"like","dislike"} or not isinstance(comment,str) or len(comment)>1400:
            return _answer({"error":"review_invalid"},400)
    except Exception:
        return _answer({"error":"invalid_json"},400)
    _db_init()
    try:
        clip=db.one("clips",clip_id)
        existing=db.one("projects",clip["project_id"])
        with db.conn() as c:
            c.execute("""INSERT INTO dashboard_feedback
                         (id,clip_id,decision,comment,created_at)
                         VALUES (?,?,?,?,?)""",
                      (db.newid("rev"),clip_id,decision,comment,db.now()))
        if decision=="dislike":
            with db.conn() as c:
                # Disapproving a queued (not-yet-uploading) clip cancels its public upload.
                c.execute("""UPDATE dashboard_publishes SET status='cancelled'
                             WHERE clip_id=? AND status='queued'""", (clip_id,))
        if decision=="like":
            if data.get("rights_confirmed") is not True:
                return _answer({"error": "Confirme os direitos de uso antes de publicar este corte."}, 403)
            qa_path=Path(clip.get("path") or "").with_suffix(".qa.json")
            qa=json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.is_file() else {}
            if clip["style"]=="split" and not qa.get("auto_publish_ready"):
                return _answer({"error": "Corte reprovado: português, legenda e foto contextual licenciada são obrigatórios antes de publicar."},422)
            title=(data.get("title") or (existing["name"] + " #Shorts"))[:100]
            description=(data.get("description") or ("Corte de " + existing["name"] + ". #Shorts"))
            description += _image_attribution(qa)
            description=description[:5000]
            result=enqueue_publication(clip_id,title=title,description=description,
                                        explicitly_approved=True,privacy="private")
            return _answer({"result":result,"action":"queued_private"},202)
        # A dislike records exactly what the owner wants changed. A new clip
        # can only be rendered if the source and word-level transcript exist.
        if clip.get("uploaded_url"):
            return _answer({"action":"feedback_recorded","note":"already_published"},202)
        if not existing.get("media") or not existing.get("transcript"):
            return _answer({"action":"feedback_recorded","note":"source_transcript_needed"},202)
        start=float(clip["start"]);end=float(clip["end"])
        duration=end-start;total=float(existing.get("duration") or 0)
        # A modest real segment change; no fake claim of semantic AI editing.
        start2=min(max(0.0,start+4.0),max(0,total-duration))
        end2=min(total,start2+duration)
        if start2==start:
            start2=max(0.0,start-5.0)
            end2=min(total,start2+duration)
        remake=pipeline.start_render_split(existing["id"],start2,end2,
                                           hook_white="NOVA VERSÃO",hook_red="EM REVISÃO")
        with db.conn() as c:
            c.execute("INSERT INTO dashboard_renders VALUES (?,?,?,?,?)",
                      (remake["clip_id"],None,remake["job_id"],"queued",db.now()))
            c.execute("""UPDATE dashboard_feedback SET remake_clip_id=?
                         WHERE clip_id=? AND decision='dislike' AND remake_clip_id IS NULL""",
                      (remake["clip_id"],clip_id))
        return _answer({"action":"remake_queued","remake":remake,
                        "note":"Intervalo reeditado automaticamente; comentário salvo para revisão humana/IA"},202)
    except (ValueError,PermissionError) as exc:
        return _answer({"error":str(exc)},400)


def _queue_one_nasa_private_validation():
    """User-requested, one-time PRIVATE E2E test with a NASA/JPL source only.

    Never auto-approves the owner's other sources. The database's unique
    publication row ensures restart/retry does not cause duplicate uploads.
    """
    if os.getenv("AUTOCLIPS_PRIVATE_VALIDATION_ENABLED") != "true":
        return
    source_id = "src_nasa_validation_20261019"
    with db.conn() as c:
        row = c.execute("""SELECT s.project_id,s.status,s.original_video_id
                 FROM dashboard_sources s WHERE s.id=?""", (source_id,)).fetchone()
        if (not row or row["status"] != "awaiting_review" or
                row["original_video_id"] != "Er5L6cxnRTc"):
            if row and not getattr(_queue_one_nasa_private_validation, "_state_reported", False):
                print("AUTOCLIPS_NASA_STATUS",
                      dict((k,row[k]) for k in ("status","project_id","original_video_id")),
                      flush=True)
                _queue_one_nasa_private_validation._state_reported=True
            return
        attempted = c.execute("""SELECT 1 FROM dashboard_publishes q
            JOIN clips k ON q.clip_id=k.id WHERE k.project_id=? LIMIT 1""",
            (row["project_id"],)).fetchone()
        if attempted:
            return
        choice = c.execute("""SELECT id FROM clips
            WHERE project_id=? AND status='ready' AND path IS NOT NULL
            ORDER BY created ASC LIMIT 1""", (row["project_id"],)).fetchone()
    if not choice:
        if not getattr(_queue_one_nasa_private_validation, "_empty_reported", False):
            with db.conn() as c:
                states = [dict(v) for v in c.execute(
                    "SELECT status, count(*) AS qty FROM clips WHERE project_id=? GROUP BY status",
                    (row["project_id"],))]
                render_states = [dict(v) for v in c.execute("""
                    SELECT r.status AS render_status,k.error AS clip_error,j.status AS job_status,
                           substr(j.error,1,180) AS job_error
                    FROM dashboard_renders r LEFT JOIN clips k ON r.clip_id=k.id
                    LEFT JOIN jobs j ON r.job_id=j.id
                    WHERE k.project_id=?""", (row["project_id"],))]
            print("AUTOCLIPS_NASA_NO_READY_CLIP", states, render_states, flush=True)
            _queue_one_nasa_private_validation._empty_reported=True
        # Retry only the single NASA validation after the old 1080p FFmpeg
        # process was killed for using more memory than the Railway worker has.
        # An atomic revision gate avoids duplicate jobs across restarts.
        revision = "nasa-private-540p-lowmem-v1"
        with db.conn() as c:
            previously_failed = c.execute(
                "SELECT 1 FROM clips WHERE project_id=? AND status='failed' LIMIT 1",
                (row["project_id"],)).fetchone()
            if previously_failed:
                claimed = c.execute("""UPDATE dashboard_sources
                    SET status='rendering',retry_revision=?,updated_at=?
                    WHERE id=? AND status='awaiting_review'
                      AND coalesce(retry_revision,'')<>?""",
                    (revision, db.now(), source_id, revision)).rowcount
            else:
                claimed = 0
        if claimed:
            try:
                project = db.one("projects", row["project_id"])
                duration = float(project["duration"] or 0)
                if duration < 16:
                    raise ValueError("Fonte de teste curta demais")
                retry = pipeline.start_render_split(
                    row["project_id"], 0.0, min(duration - 0.25, 32.0))
                with db.conn() as c:
                    c.execute("""INSERT INTO dashboard_renders
                       (clip_id,source_id,job_id,status,created_at)
                       VALUES (?,?,?,'queued',?)""",
                       (retry["clip_id"],source_id,retry["job_id"],db.now()))
                print("AUTOCLIPS_NASA_LOW_MEM_RETRY_QUEUED",
                      retry["clip_id"], flush=True)
            except Exception as exc:
                print("AUTOCLIPS_NASA_LOW_MEM_RETRY_FAILED",
                      type(exc).__name__, flush=True)
                with db.conn() as c:
                    c.execute("UPDATE dashboard_sources SET status='failed' WHERE id=?",
                              (source_id,))
        return
    try:
        result = enqueue_publication(
            choice["id"],
            title="AutoClips | Teste privado NASA JPL - Planetas anões",
            description=("Validação privada do fluxo automático AutoClips AI. "
                         "Vídeo de origem: NASA/JPL-Caltech, "
                         "https://www.youtube.com/watch?v=Er5L6cxnRTc. "
                         "Corte e legendas produzidos automaticamente. #Shorts"),
            explicitly_approved=True, privacy="private")
        print("AUTOCLIPS_NASA_PRIVATE_TEST_QUEUED", result["clip_id"], flush=True)
    except Exception as exc:
        print("AUTOCLIPS_NASA_PRIVATE_TEST_DEFERRED", type(exc).__name__, flush=True)


def _image_attribution(qa: dict) -> str:
    """CC BY 4.0 requires author, source, licence and modification notice."""
    if qa.get("image_mode") != "wikimedia_cc_by":
        return ""
    return ("\\nFoto do painel inferior: " + str(qa.get("image_credit") or "") +
            "\\nArquivo original: " + str(qa.get("image_source_url") or "") +
            "\\nLicença: " + str(qa.get("image_license_url") or "") +
            "\\nAdaptação: recorte e redimensionamento para vídeo vertical.")[0:750]


def _queue_one_approved_chat_source():
    """One private upload per explicitly rights-cleared chat source, never public."""
    with db.conn() as c:
        rows = c.execute("""SELECT s.id,s.project_id,s.title,p.original_video_id
            FROM dashboard_sources s
            JOIN chat_ingest_permissions p ON s.id=p.source_id
            WHERE s.status='awaiting_review'
              AND p.private_publish_approved=1 AND p.rights_confirmed=1
              AND NOT EXISTS(
                SELECT 1 FROM dashboard_publishes q JOIN clips k
                ON q.clip_id=k.id WHERE k.project_id=s.project_id)
            ORDER BY s.created_at LIMIT 1""").fetchall()
        if not rows:
            return
        row = rows[0]
        clip = c.execute("""SELECT id FROM clips
            WHERE project_id=? AND status='ready' AND path IS NOT NULL
            ORDER BY created ASC LIMIT 1""", (row["project_id"],)).fetchone()
    if not clip:
        return
    try:
        media = db.one("clips",clip["id"])
        qa_path=Path(media["path"]).with_suffix(".qa.json")
        qa=json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.is_file() else {}
        if not qa.get("auto_publish_ready"):
            print("AUTOCLIPS_CHAT_PRIVATE_QUALITY_REVIEW_REQUIRED",clip["id"],flush=True)
            return
        result = enqueue_publication(
            clip["id"],
            title=(row["title"][:78] + " #Shorts")[:100],
            description=("AutoClips AI - edição de vídeo com direitos "
                         "de uso confirmados pelo responsável. "
                         "Fonte: https://www.youtube.com/watch?v=" +
                         row["original_video_id"] + " #Shorts" +
                         _image_attribution(qa)),
            explicitly_approved=True,privacy="private")
        print("AUTOCLIPS_CHAT_PRIVATE_TEST_QUEUED",result["clip_id"],flush=True)
    except Exception as exc:
        print("AUTOCLIPS_CHAT_PRIVATE_TEST_DEFERRED",type(exc).__name__,flush=True)


def _tick():
    _db_init()
    # Start at most one source import at a time; the CPU only has two render workers.
    with db.conn() as c:
        active=c.execute("""SELECT count(*) FROM dashboard_sources
                            WHERE status IN ('importing','rendering')""").fetchone()[0]
        row=c.execute("""SELECT * FROM dashboard_sources WHERE status='queued'
                         ORDER BY created_at LIMIT 1""").fetchone() if not active else None
    if row:
        # Preserve the 500 MB volume for reviewable rendered clips.
        import shutil
        if shutil.disk_usage(home()).free < 95 * 1024 * 1024:
            print("AUTOCLIPS_SOURCE_QUEUE_PAUSED_STORAGE_LOW",flush=True)
            row = None
    # A paused importer must not pause render status checks or YouTube uploads.
    if row:
        try:
            print("AUTOCLIPS_SOURCE_QUEUE_START", row["id"], row["source_kind"], flush=True)
            res=pipeline.new_project(row["link"],source_kind=row["source_kind"],
                                     authorized=True,auto_transcribe=True)
            with db.conn() as c:
                if row["title"]:
                    c.execute("UPDATE projects SET name=? WHERE id=?", (row["title"],res["project_id"]))
                c.execute("""UPDATE dashboard_sources SET status='importing',
                             project_id=?,job_id=?,updated_at=? WHERE id=?""",
                          (res["project_id"],res["job_id"],db.now(),row["id"]))
        except Exception as exc:
            with db.conn() as c:
                c.execute("""UPDATE dashboard_sources SET status='failed',error=?,
                             updated_at=? WHERE id=?""",(str(exc)[:450],db.now(),row["id"]))
    with db.conn() as c:
        running=c.execute("""SELECT * FROM dashboard_sources
                             WHERE status='importing' LIMIT 2""").fetchall()
    for row in running:
        try:
            job=pipeline.job_status(row["job_id"])
            if job["status"] in {"failed","interrupted"}:
                original_error = str(job.get("error") or "import_failed")
                if ("not a bot" in original_error.lower() or
                    "sign in to confirm" in original_error.lower()):
                    original_error = ("O YouTube bloqueou a fonte mesmo usando os clientes "
                                      "alternativos. A falha ficará registrada; nenhum Short "
                                      "falso será produzido. O sistema não precisa que você "
                                      "envie arquivos manualmente.")
                with db.conn() as c:
                    c.execute("""UPDATE dashboard_sources SET status='failed',error=?,
                                 updated_at=? WHERE id=?""",
                              (original_error[:450],db.now(),row["id"]))
            elif job["status"]=="completed":
                project=pipeline.db.one("projects",row["project_id"])
                if not project.get("transcript"):
                    raise ValueError("Source has no transcript")
                duration=float(project.get("duration") or 0)
                transcript=load_transcript(project["transcript"])
                desired = 1 if duration < 180 else (2 if duration < 360 else 3)
                picks = select_contextual_portuguese_clips(
                    transcript,duration,count=desired)
                if not picks:
                    raise ValueError("Revisão necessária: não encontrei gancho em português com começo, desenvolvimento e fim.")
                print("AUTOCLIPS_PT_EDITORIAL_SELECTED",row["id"],len(picks),flush=True)
                for item in picks:
                    started=pipeline.start_render_split(row["project_id"],
                                                        float(item["start"]),float(item["end"]))
                    with db.conn() as c:
                        c.execute("INSERT OR IGNORE INTO dashboard_renders VALUES (?,?,?,?,?)",
                                  (started["clip_id"],row["id"],started["job_id"],"queued",db.now()))
                with db.conn() as c:
                    c.execute("""UPDATE dashboard_sources SET status='rendering',
                                 updated_at=? WHERE id=?""",(db.now(),row["id"]))
        except Exception as exc:
            with db.conn() as c:
                c.execute("""UPDATE dashboard_sources SET status='failed',error=?,
                             updated_at=? WHERE id=?""",(str(exc)[:450],db.now(),row["id"]))
    with db.conn() as c:
        renders=c.execute("SELECT * FROM dashboard_renders WHERE status='queued' LIMIT 30").fetchall()
    for r in renders:
        try:
            job=pipeline.job_status(r["job_id"])
            if job["status"] in {"completed","failed","interrupted"}:
                with db.conn() as c:
                    c.execute("UPDATE dashboard_renders SET status=? WHERE clip_id=?",
                              ("ready" if job["status"]=="completed" else "failed",r["clip_id"]))
                if job["status"]=="completed":
                    _safe_quality_audit(r["clip_id"])
        except Exception:
            pass
    with db.conn() as c:
        c.execute("""UPDATE dashboard_sources SET status='awaiting_review',
                     updated_at=? WHERE status='rendering' AND NOT EXISTS (
                     SELECT 1 FROM dashboard_renders r
                     WHERE r.source_id=dashboard_sources.id AND r.status='queued')""",(db.now(),))
    _queue_one_nasa_private_validation()
    _queue_one_approved_chat_source()
    publish_next()


def _prune_failed_hosted_imports() -> int:
    """Free only abandoned failed imported sources, never a ready/review clip."""
    root = (home() / "projects").resolve()
    released = 0
    with db.conn() as c:
        candidates = c.execute("""SELECT p.id,p.media FROM projects p
                WHERE p.source_kind='hosted'
                AND p.status IN ('failed','transcription_failed')
                AND NOT EXISTS (SELECT 1 FROM clips k WHERE k.project_id=p.id)
                AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.target_id=p.id
                                AND j.status IN ('queued','running'))""").fetchall()
    for row in candidates:
        folder = (root / row["id"]).resolve()
        if folder.parent != root or not folder.is_dir():
            continue
        for filename in ("source.mp4","source_compressed.mp4","source.mp4.part"):
            target = folder / filename
            try:
                if target.is_file() and not target.is_symlink():
                    size = target.stat().st_size
                    target.unlink()
                    released += size
            except OSError:
                continue
    if released:
        print("AUTOCLIPS_ORPHANED_FAILED_IMPORTS_FREED_BYTES", released, flush=True)
    return released


def _archive_reviewed_sources() -> int:
    """Free working disk without losing source media or reviewable clips.

    Archive only finished sources whose every clip was rendered successfully.
    The private S3 object is checksummed and HEAD-verified before local removal.
    """
    from . import source_archive
    import shutil

    if not source_archive.configured():
        if not getattr(_archive_reviewed_sources, "_warned_config", False):
            print("AUTOCLIPS_ARCHIVE_NOT_CONFIGURED", flush=True)
            _archive_reviewed_sources._warned_config = True
        return 0
    free = shutil.disk_usage(home()).free
    if free >= 240 * 1024 * 1024:
        return 0
    with db.conn() as c:
        candidates = c.execute("""SELECT p.id,p.media FROM projects p
            JOIN dashboard_sources s ON s.project_id=p.id
            WHERE s.status IN ('awaiting_review','failed') AND p.media IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM jobs j WHERE
                           (j.target_id=p.id OR j.target_id IN (
                             SELECT k.id FROM clips k WHERE k.project_id=p.id))
                           AND j.status IN ('queued','running'))
            ORDER BY s.updated_at ASC""").fetchall()
    if not candidates:
        if not getattr(_archive_reviewed_sources, "_warned_candidates", False):
            with db.conn() as c:
                snapshot = [dict(x) for x in c.execute(
                    "SELECT status,count(*) AS count FROM dashboard_sources GROUP BY status")]
            details = []
            with db.conn() as c:
                details = [dict(v) for v in c.execute("""
                    SELECT s.status AS source_status,p.status AS project_status,
                           count(*) AS projects_with_media
                    FROM dashboard_sources s JOIN projects p ON p.id=s.project_id
                    WHERE p.media IS NOT NULL GROUP BY s.status,p.status""")]
            print("AUTOCLIPS_ARCHIVE_NO_SAFE_CANDIDATES", snapshot, details, flush=True)
            _archive_reviewed_sources._warned_candidates = True
        return 0
    root = (home() / "projects").resolve()
    released = 0
    for row in candidates:
        path = Path(row["media"]).resolve()
        expected_parent = (root / row["id"]).resolve()
        if path.parent != expected_parent or expected_parent.parent != root:
            continue
        try:
            released += source_archive.archive_source(row["id"], path)
        except Exception as exc:
            print("AUTOCLIPS_SOURCE_ARCHIVE_DEFERRED",
                  row["id"], type(exc).__name__, flush=True)
        if shutil.disk_usage(home()).free >= 240 * 1024 * 1024:
            break
    return released


def _queue_one_portuguese_quality_retest():
    """Re-cut one already-imported PT source, once, without duplicate downloads.

    A source must already have a transcript and no active jobs; this never
    grants copyright, queues uploads or removes the owner's earlier clips.
    """
    if os.getenv("AUTOCLIPS_PT_QUALITY_RETEST") != "true":
        return
    import shutil
    if shutil.disk_usage(home()).free < 225 * 1024 * 1024:
        return
    with db.conn() as c:
        active=c.execute("""SELECT count(*) FROM dashboard_sources
                 WHERE status IN ('importing','rendering')""").fetchone()[0]
        if active:
            return
        row=c.execute("""SELECT s.id,s.project_id,p.transcript,p.duration
             FROM dashboard_sources s JOIN projects p ON p.id=s.project_id
             WHERE s.status='awaiting_review'
               AND s.original_video_id IN ('PRQ_7aZtnqg','e2Mou7KYXyo','cbmRw1Y9QPQ')
               AND p.transcript IS NOT NULL
               AND NOT EXISTS(SELECT 1 FROM dashboard_quality_retests r
                              WHERE r.source_id=s.id)
             ORDER BY CASE s.original_video_id WHEN 'PRQ_7aZtnqg' THEN 0 WHEN 'e2Mou7KYXyo' THEN 1 ELSE 2 END
             LIMIT 1""").fetchone()
    if not row:
        return
    try:
        transcript=load_transcript(row["transcript"])
        picks=select_contextual_portuguese_clips(transcript,float(row["duration"] or 0),count=1)
        if not picks:
            result="needs_editorial_review"
        else:
            result="claimed"
        with db.conn() as c:
            ok=c.execute("""INSERT OR IGNORE INTO dashboard_quality_retests
                (source_id,project_id,status,created_at) VALUES (?,?,?,?)""",
                (row["id"],row["project_id"],result,db.now())).rowcount
        if not ok or not picks:
            if not picks:
                print("AUTOCLIPS_PT_QUALITY_NO_STRONG_HOOK",row["id"],flush=True)
            return
        item=picks[0]
        planned=pipeline.start_render_split(row["project_id"],
                       float(item["start"]),float(item["end"]))
        with db.conn() as c:
            c.execute("UPDATE dashboard_quality_retests SET clip_id=?,status='rendering' WHERE source_id=?",
                      (planned["clip_id"],row["id"]))
            c.execute("""INSERT OR IGNORE INTO dashboard_renders
                         (clip_id,source_id,job_id,status,created_at)
                         VALUES (?,?,?,'queued',?)""",
                      (planned["clip_id"],row["id"],planned["job_id"],db.now()))
            c.execute("""UPDATE dashboard_sources SET status='rendering',updated_at=?
                         WHERE id=?""",(db.now(),row["id"]))
        print("AUTOCLIPS_PT_QUALITY_RETEST_QUEUED",row["id"],planned["clip_id"],flush=True)
    except Exception as exc:
        print("AUTOCLIPS_PT_QUALITY_RETEST_DEFERRED",type(exc).__name__,flush=True)


def _queue_one_missing_context_photo_repair() -> None:
    """Once per source, re-render a verified PT preview with a licensed photo.

    Keep original clips and approvals untouched; this is a review render,
    never a publication. Atomic DB claim and a single active worker prevent
    duplicate concurrent renders if the service restarts.
    """
    if os.getenv("AUTOCLIPS_PT_IMAGE_REPAIR") != "true":
        return
    import shutil
    if shutil.disk_usage(home()).free < 225 * 1024 * 1024:
        return
    _db_init()
    with db.conn() as c:
        active=c.execute("""SELECT count(*) FROM dashboard_sources
                           WHERE status IN ('importing','rendering')""").fetchone()[0]
        running=c.execute("""SELECT count(*) FROM jobs WHERE status IN ('queued','running')""").fetchone()[0]
        if active or running:
            return
        row=c.execute("""SELECT s.id AS source_id,s.project_id,k.id AS old_clip_id,
                                k.start AS cut_start,k.end AS cut_end,k.path
            FROM dashboard_sources s
            JOIN dashboard_quality_retests q ON q.source_id=s.id
            JOIN clips k ON k.id=q.clip_id
            WHERE s.status='awaiting_review' AND k.status='ready'
              AND s.original_video_id IN ('e2Mou7KYXyo','cbmRw1Y9QPQ')
              AND NOT EXISTS(SELECT 1 FROM dashboard_image_repairs repair
                             WHERE repair.source_id=s.id)
            ORDER BY CASE s.original_video_id
                      WHEN 'e2Mou7KYXyo' THEN 0 ELSE 1 END LIMIT 1""").fetchone()
    if not row:
        return
    path=Path(row["path"] or "")
    qa_path=path.with_suffix(".qa.json")
    try:
        qa=json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.is_file() else {}
        if qa.get("language") != "pt" or qa.get("image_mode") != "source_frame_preview_only":
            return
        if not qa.get("caption_events", 0):
            return
        with db.conn() as c:
            claimed=c.execute("""INSERT OR IGNORE INTO dashboard_image_repairs
                (source_id,old_clip_id,status,created_at) VALUES (?,?,?,?)""",
                (row["source_id"],row["old_clip_id"],"claimed",db.now())).rowcount
        if not claimed:
            return
        render_job=pipeline.start_render_split(
            row["project_id"],float(row["cut_start"]),float(row["cut_end"]))
        with db.conn() as c:
            c.execute("""UPDATE dashboard_image_repairs
                         SET new_clip_id=?,status='rendering' WHERE source_id=?""",
                      (render_job["clip_id"],row["source_id"]))
            c.execute("""INSERT OR IGNORE INTO dashboard_renders
                (clip_id,source_id,job_id,status,created_at)
                VALUES (?,NULL,?,'queued',?)""",
                (render_job["clip_id"],render_job["job_id"],db.now()))
        print("AUTOCLIPS_CONTEXT_IMAGE_REPAIR_QUEUED",row["source_id"],
              render_job["clip_id"],flush=True)
    except Exception as exc:
        print("AUTOCLIPS_CONTEXT_IMAGE_REPAIR_DEFERRED",row["source_id"],
              type(exc).__name__,flush=True)
        with db.conn() as c:
            c.execute("""UPDATE dashboard_image_repairs SET status='failed'
                         WHERE source_id=? AND status='claimed'""",(row["source_id"],))


def _worker():
    while True:
        try:
            _prune_failed_hosted_imports()
            _archive_reviewed_sources()
            _queue_one_portuguese_quality_retest()
            _queue_one_missing_context_photo_repair()
            _tick()
        except Exception as exc:
            print("AUTOCLIPS_DASHBOARD_WORKER_ERROR",type(exc).__name__,flush=True)
        time.sleep(15)


def _safe_quality_audit(clip_id: str) -> None:
    """Log only nonsecret language/layout/image readiness for QA."""
    try:
        item=db.one("clips",clip_id)
        path=Path(item.get("path") or "")
        qa_path=path.with_suffix(".qa.json")
        if not qa_path.is_file():
            return
        qa=json.loads(qa_path.read_text(encoding="utf-8"))
        print("AUTOCLIPS_QUALITY_AUDIT",clip_id,
              "language",qa.get("language"),
              "image_mode",qa.get("image_mode"),
              "captions",qa.get("caption_events"),
              "publish_ready",qa.get("auto_publish_ready"),flush=True)
    except Exception:
        pass


def start_background_worker():
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _db_init()
    # Include previously rendered clips after a restart, without reopening media
    # or leaking signed URLs/tokens into logs.
    with db.conn() as c:
        audit_ids=[v["id"] for v in c.execute("""SELECT id FROM clips WHERE status='ready'
                                                ORDER BY created DESC LIMIT 12""")]
    for clip_id in audit_ids:
        _safe_quality_audit(clip_id)
    t=threading.Thread(target=_worker,name="autoclips-review-publish",daemon=True)
    t.start()
    _WORKER_STARTED=True


async def upload_ready(request):
    """Owner-uploaded, already edited portrait MP4, eligible for review and like."""
    err = _auth(request, write=True)
    if err: return err
    if request.headers.get("content-type","").split(";",1)[0] not in ("video/mp4","application/octet-stream"):
        return _answer({"error": "mp4_required"}, 415)
    try:
        size = int(request.headers.get("content-length", "-1"))
    except ValueError:
        return _answer({"error":"bad_file_size"},400)
    if not 1000 <= size <= 180*1024*1024:
        return _answer({"error":"file_size_outside_limit"},413)
    _db_init()
    ident=db.newid("clip")
    target=home()/"imports"/(ident+"_owner.mp4")
    tmp=target.with_suffix(".part")
    length=0
    try:
        with tmp.open("wb") as fd:
            async for chunk in request.stream():
                length+=len(chunk)
                if length>180*1024*1024:
                    return _answer({"error":"upload_too_large"},413)
                fd.write(chunk)
        if length!=size:
            return _answer({"error":"incomplete_upload"},422)
        os.replace(tmp,target)
        # Deduplicate the specifically approved 80s Cariani original, even if
        # the private GitHub ingestion workflow executes later. Both routes use
        # the SAME fixed clip_id and publication record.
        from .demo_ingest import DEMO_SHA, _existing_demo
        exact_demo = hashlib.sha256(target.read_bytes()).hexdigest() == DEMO_SHA
        if exact_demo:
            existing = _existing_demo()
            if existing:
                target.unlink(missing_ok=True)
                return _answer({"clip_id":existing["id"],"status":existing["status"],
                                "url":existing["uploaded_url"],"duplicate":True})
        from .media import probe
        info=probe(target)
        if not 1<=float(info["duration"])<=180 or not (info.get("width")>0 and info.get("height")>info.get("width")):
            target.unlink(missing_ok=True)
            return _answer({"error":"requires_vertical_video_up_to_180s"},422)
        project_id="prj_cariani_demo80" if exact_demo else db.newid("prj")
        if exact_demo:
            ident="clip_cariani_demo80"
        with db.conn() as c:
            c.execute("""INSERT INTO projects
                         (id,source_kind,source,name,media,transcript,duration,status,error,created)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (project_id,"file",target.name,"Short enviado pelo proprietário",
                       str(target),None,float(info["duration"]),"ready",None,db.now()))
            c.execute("""INSERT INTO clips
                         (id,project_id,start,end,style,path,status,error,created,uploaded_url)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (ident,project_id,0,float(info["duration"]),"split",str(target),
                       "ready",None,db.now(),None))
        return _answer({"clip_id":ident,"duration":info["duration"],"status":"ready"},201)
    except Exception as exc:
        target.unlink(missing_ok=True)
        print("DASHBOARD_MP4_UPLOAD_ERROR",type(exc).__name__,flush=True)
        return _answer({"error":"upload_failed","type":type(exc).__name__},500)
    finally:
        tmp.unlink(missing_ok=True)


async def upload_source(request):
    """Upload compressed original footage (not pre-edited) and queue actual AutoClips cuts."""
    err = _auth(request, write=True)
    if err: return err
    if request.headers.get("content-type", "").split(";",1)[0] not in ("video/mp4", "application/octet-stream"):
        return _answer({"error": "mp4_required"}, 415)
    try:
        declared_size = int(request.headers.get("content-length", "-1"))
    except ValueError:
        return _answer({"error": "invalid_file_size"}, 400)
    max_bytes = 180 * 1024 * 1024
    if not 1024 <= declared_size <= max_bytes:
        return _answer({"error": "video_source_must_be_under_180_mb"}, 413)
    _db_init()
    with db.conn() as conn:
        active = conn.execute("""SELECT count(*) FROM dashboard_sources
                                 WHERE status IN ('queued','importing','rendering')""").fetchone()[0]
        if active >= 60:
            return _answer({"error": "source_queue_full"}, 429)

    sid = db.newid("src")
    filename = sid + "_original.mp4"
    file_path = home() / "imports" / filename
    tmp = file_path.with_suffix(".part")
    count = 0
    try:
        with tmp.open("wb") as fd:
            async for chunk in request.stream():
                count += len(chunk)
                if count > max_bytes:
                    return _answer({"error": "source_too_large"}, 413)
                fd.write(chunk)
        if count != declared_size:
            return _answer({"error": "incomplete_video_upload"}, 422)
        os.replace(tmp, file_path)
        from .media import probe
        metadata = probe(file_path)
        if not 10 <= float(metadata.get("duration") or 0) <= 60*60*4:
            return _answer({"error": "unsupported_video_duration"}, 422)
        with db.conn() as conn:
            conn.execute("""INSERT INTO dashboard_sources
                            (id,link,source_kind,status,created_at,updated_at)
                            VALUES (?,?,'file','queued',?,?)""",
                         (sid,filename,db.now(),db.now()))
        return _answer({"id":sid,"status":"queued","duration":metadata["duration"],
                        "size_bytes":count,"next":"transcription_and_clips"},201)
    except Exception as exc:
        print("DASHBOARD_SOURCE_UPLOAD_ERROR",type(exc).__name__,flush=True)
        return _answer({"error": "source_upload_failed","type":type(exc).__name__},500)
    finally:
        tmp.unlink(missing_ok=True)
        # Delete invalid files, retain only uploads that have an accepted queue row.
        with db.conn() as conn:
            accepted = conn.execute("SELECT 1 FROM dashboard_sources WHERE id=?", (sid,)).fetchone()
        if not accepted:
            file_path.unlink(missing_ok=True)
