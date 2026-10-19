"""Idempotent 20/day public publishing queue, Sao Paulo date boundary.

Explicit right-swipe approval is required for each new clip. An attempted upload
is counted for the day even if the API later errors, and is never automatically
retried after ambiguous network failure (avoid duplicate public videos).
"""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import database as db
from . import pipeline

MAX_DAILY_PUBLICATIONS = 20
TZ = ZoneInfo("America/Sao_Paulo")


def local_day() -> str:
    return datetime.now(TZ).date().isoformat()


def create_tables() -> None:
    pipeline.init()
    with db.conn() as c:
        c.executescript("""
          CREATE TABLE IF NOT EXISTS dashboard_publishes (
            clip_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            publication_day TEXT,
            started_at TEXT,
            completed_at TEXT,
            youtube_url TEXT,
            error TEXT
          );
          CREATE INDEX IF NOT EXISTS dashboard_publishes_day
            ON dashboard_publishes(publication_day,status);
        """)


def get_publication(clip_id: str) -> dict | None:
    create_tables()
    with db.conn() as c:
        row = c.execute("SELECT * FROM dashboard_publishes WHERE clip_id=?", (clip_id,)).fetchone()
        return dict(row) if row else None


def daily_status() -> dict:
    create_tables()
    day = local_day()
    with db.conn() as c:
        used = c.execute("""SELECT count(*) FROM dashboard_publishes
                            WHERE publication_day=? AND status IN
                            ('publishing','published','failed_review')""", (day,)).fetchone()[0]
        queued = c.execute("SELECT count(*) FROM dashboard_publishes WHERE status='queued'").fetchone()[0]
    return {"day": day, "used": used, "limit": MAX_DAILY_PUBLICATIONS,
            "remaining": max(0, MAX_DAILY_PUBLICATIONS-used), "queued": queued}


def enqueue_publication(clip_id: str, *, title: str, description: str,
                        explicitly_approved: bool = False) -> dict:
    if not explicitly_approved:
        raise PermissionError("Publicação exige curtir/aprovar o vídeo expressamente")
    if not 1 <= len(title.strip()) <= 100 or len(description) > 5000:
        raise ValueError("Título ou descrição YouTube inválidos")
    create_tables()
    clip = db.one("clips", clip_id)
    if clip["status"] != "ready" or not clip.get("path"):
        raise ValueError("Vídeo ainda não está pronto para publicação")
    if clip.get("uploaded_url"):
        return {"clip_id": clip_id, "status": "published", "url": clip["uploaded_url"]}
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT status,youtube_url FROM dashboard_publishes WHERE clip_id=?",
                        (clip_id,)).fetchone()
        if row:
            return {"clip_id": clip_id, "status": row["status"], "url": row["youtube_url"]}
        c.execute("""INSERT INTO dashboard_publishes
                      (clip_id,title,description,status,requested_at)
                      VALUES (?,?,?,'queued',?)""",
                  (clip_id, title.strip(), description, db.now()))
    return {"clip_id": clip_id, "status": "queued", "privacy": "public",
            "quota": daily_status()}


def publish_next() -> dict | None:
    create_tables()
    today = local_day()
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        busy = c.execute("SELECT count(*) FROM dashboard_publishes WHERE status='publishing'").fetchone()[0]
        if busy:
            return None  # ensure only one video-upload attempt at a time
        used = c.execute("""SELECT count(*) FROM dashboard_publishes
                            WHERE publication_day=? AND status IN
                            ('publishing','published','failed_review')""", (today,)).fetchone()[0]
        if used >= MAX_DAILY_PUBLICATIONS:
            return {"status": "limit_reached", "day": today}
        row = c.execute("""SELECT * FROM dashboard_publishes WHERE status='queued'
                            ORDER BY requested_at ASC LIMIT 1""").fetchone()
        if not row:
            return None
        clip_id = row["clip_id"]
        updated = c.execute("""UPDATE dashboard_publishes SET status='publishing',
                               publication_day=?,started_at=?,error=NULL
                               WHERE clip_id=? AND status='queued'""",
                            (today, db.now(), clip_id)).rowcount
        if not updated:
            return None
        queued = dict(row)

    # Never auto-resend a clip following a partial upload or a timeout.
    try:
        from .youtube import channel, upload
        clip = db.one("clips", queued["clip_id"])
        if clip.get("uploaded_url"):
            url = clip["uploaded_url"]
        else:
            channel_id = channel()["id"]
            url = upload(clip["path"], queued["title"], queued["description"],
                         "public", False, channel_id, None)
            db.update("clips", clip["id"], uploaded_url=url)
        with db.conn() as c:
            c.execute("""UPDATE dashboard_publishes SET status='published',
                         youtube_url=?,completed_at=? WHERE clip_id=?""",
                      (url, db.now(), clip["id"]))
        print("AUTOCLIPS_PUBLICATION_SUCCESS", clip["id"], url, flush=True)
        return {"status": "published", "clip_id": clip["id"], "url": url}
    except Exception as exc:
        # Do not retry automatically: Google may have completed the upload.
        with db.conn() as c:
            c.execute("""UPDATE dashboard_publishes SET status='failed_review',
                         error=? WHERE clip_id=?""", (str(exc)[:1000], queued["clip_id"]))
        print("AUTOCLIPS_PUBLICATION_NEEDS_REVIEW", queued["clip_id"],
              type(exc).__name__, flush=True)
        return {"status": "failed_review", "clip_id": queued["clip_id"],
                "error_type": type(exc).__name__}
