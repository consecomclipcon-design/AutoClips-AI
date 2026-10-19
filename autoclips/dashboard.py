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
        """)


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
            title=(data.get("title") or (existing["name"] + " #Shorts"))[:100]
            description=(data.get("description") or ("Corte de " + existing["name"] + ". #Shorts"))[:5000]
            result=enqueue_publication(clip_id,title=title,description=description,explicitly_approved=True)
            return _answer({"result":result,"action":"queued_public"},202)
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


def _tick():
    _db_init()
    # Start at most one source import at a time; the CPU only has two render workers.
    with db.conn() as c:
        active=c.execute("""SELECT count(*) FROM dashboard_sources
                            WHERE status IN ('importing','rendering')""").fetchone()[0]
        row=c.execute("""SELECT * FROM dashboard_sources WHERE status='queued'
                         ORDER BY created_at LIMIT 1""").fetchone() if not active else None
    if row:
        try:
            res=pipeline.new_project(row["link"],source_kind=row["source_kind"],
                                     authorized=True,auto_transcribe=True)
            with db.conn() as c:
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
                with db.conn() as c:
                    c.execute("""UPDATE dashboard_sources SET status='failed',error=?,
                                 updated_at=? WHERE id=?""",
                              (str(job.get("error") or "import_failed")[:450],db.now(),row["id"]))
            elif job["status"]=="completed":
                project=pipeline.db.one("projects",row["project_id"])
                if not project.get("transcript"):
                    raise ValueError("Source has no transcript")
                picks=pipeline.suggest_clips(row["project_id"],count=3,
                                             min_seconds=35,max_seconds=90)["suggestions"]
                if not picks: raise ValueError("No promising sections found")
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
        except Exception:
            pass
    with db.conn() as c:
        c.execute("""UPDATE dashboard_sources SET status='awaiting_review',
                     updated_at=? WHERE status='rendering' AND NOT EXISTS (
                     SELECT 1 FROM dashboard_renders r
                     WHERE r.source_id=dashboard_sources.id AND r.status='queued')""",(db.now(),))
    publish_next()


def _worker():
    while True:
        try:
            _tick()
        except Exception as exc:
            print("AUTOCLIPS_DASHBOARD_WORKER_ERROR",type(exc).__name__,flush=True)
        time.sleep(15)


def start_background_worker():
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _db_init()
    t=threading.Thread(target=_worker,name="autoclips-review-publish",daemon=True)
    t.start()
    _WORKER_STARTED=True
