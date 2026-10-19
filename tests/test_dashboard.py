"""Regression tests for owner dashboard and 20/day private test publication queue."""
import os
import asyncio
from pathlib import Path
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from autoclips import database as db, dashboard, publish_queue, pipeline


@pytest.fixture
def working(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME",str(tmp_path))
    monkeypatch.setenv("MCP_GATEWAY_TOKEN","demo-gateway-key-very-long-and-safe-for-tests-0123")
    monkeypatch.setenv("AUTOCLIPS_DASHBOARD_PASSWORD","test-owner-password-is-secure")
    pipeline.init()
    dashboard._db_init()
    return tmp_path


def add_clip(root, i):
    clip=f"clip_{i:012d}"
    project=f"prj_{i:012d}"
    f=root/"imports"/(clip+".mp4")
    f.write_bytes(b"unit-test-mp4")
    with db.conn() as c:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (project,"file","demo.mp4","Demo",str(f),None,80,"ready",None,db.now()))
        c.execute("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (clip,project,0,80,"split",str(f),"ready",None,db.now(),None))
    return clip


def test_youtube_bot_failure_retry_once_for_new_strategy(working):
    source_id="src_automatic_retry_test"
    with db.conn() as c:
        c.execute("""INSERT INTO dashboard_sources
                     (id,link,source_kind,status,error,created_at,updated_at)
                     VALUES (?,?,'youtube','failed',?,?,?)""",
                  (source_id,"https://www.youtube.com/watch?v=NmjiNtvSkFk",
                   "ERROR: Sign in to confirm you're not a bot",db.now(),db.now()))
    dashboard._db_init()
    with db.conn() as c:
        row=c.execute("SELECT status,auto_retry_count,retry_revision FROM dashboard_sources WHERE id=?",
                      (source_id,)).fetchone()
        assert row["status"]=="queued"
        assert row["auto_retry_count"]==1
        assert row["retry_revision"]=="dualstack-pot-v1"
        c.execute("UPDATE dashboard_sources SET status='failed', error=? WHERE id=?",
                  ("Download do YouTube bloqueado",source_id))
    for _ in range(5):
        dashboard._db_init()  # frequent UI polling must NOT trigger retries
    with db.conn() as c:
        row=c.execute("SELECT status,auto_retry_count FROM dashboard_sources WHERE id=?",(source_id,)).fetchone()
    assert row["status"]=="failed"
    assert row["auto_retry_count"]==1


def test_private_approval_requires_explicit_consent(working):
    clip=add_clip(working,1)
    with pytest.raises(PermissionError):
        publish_queue.enqueue_publication(clip,title="Short",description="Test")
    r=publish_queue.enqueue_publication(clip,title="Short",description="Test",explicitly_approved=True)
    assert r["status"]=="queued"
    assert publish_queue.enqueue_publication(clip,title="Short",description="Test",explicitly_approved=True)["status"]=="queued"


def test_no_more_than_20_uploads_on_same_day(working,monkeypatch):
    from autoclips import youtube
    monkeypatch.setattr(youtube,"channel",lambda:{"id":"UC"+"x"*22,"name":"ClipCon"})
    uploaded=[]
    def fake_upload(file_path,title,description,privacy,made_for_kids,channel_id,publish_at):
        assert privacy=="private" and channel_id=="UC"+"x"*22
        uploaded.append(file_path)
        return "https://www.youtube.com/watch?v=ABCDEF12345"
    monkeypatch.setattr(youtube,"upload",fake_upload)
    for i in range(21):
        publish_queue.enqueue_publication(add_clip(working,i+100),
                                          title=f"Short {i+1}",description="Corte de teste",
                                          explicitly_approved=True)
    for _ in range(20):
        assert publish_queue.publish_next()["status"]=="published"
    assert publish_queue.publish_next()["status"]=="limit_reached"
    assert len(uploaded)==20
    s=publish_queue.daily_status()
    assert s["used"]==20 and s["queued"]==1


def test_failed_upload_not_retried_automatically(working,monkeypatch):
    from autoclips import youtube
    monkeypatch.setattr(youtube,"channel",lambda:{"id":"UC"+"x"*22})
    attempts=[]
    def fake_upload(*a,**kw):
        attempts.append(1)
        raise TimeoutError("Google may have accepted an ambiguous upload")
    monkeypatch.setattr(youtube,"upload",fake_upload)
    clip=add_clip(working,6)
    publish_queue.enqueue_publication(clip,title="Short",description="",explicitly_approved=True)
    assert publish_queue.publish_next()["status"]=="failed_review"
    assert publish_queue.publish_next() is None
    assert len(attempts)==1
    assert publish_queue.daily_status()["used"]==1


def test_dashboard_login_cookie_csrf_and_feed(working):
    app=Starlette(routes=[
        Route("/auth/login",dashboard.login,methods=["POST"]),
        Route("/auth/session",dashboard.session),
        Route("/api/console/feed",dashboard.feed),
        Route("/api/console/links",dashboard.add_links,methods=["POST"]),
    ])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        assert c.get("/api/console/feed").status_code==401
        assert c.post("/auth/login",json={"password":"wrong"}).status_code==401
        resp=c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        assert resp.status_code==200 and "httponly" in resp.headers["set-cookie"].lower()
        assert c.get("/auth/session").json()["loggedIn"] is True
        assert c.get("/api/console/feed").status_code==200
        assert c.post("/api/console/links",json={"links":"https://youtu.be/q6OYTqiXmAw","authorized":True}).status_code==403
        r=c.post("/api/console/links",json={"links":"https://youtu.be/q6OYTqiXmAw","authorized":True},
            headers={"X-AutoClips-Action":"1","Origin":"https://autoclips-worker-production.up.railway.app"})
        assert r.status_code==202 and r.json()["items"][0]["status"]=="queued"


def test_login_ui_api_route_contract_and_existing_tab_compatibility(working):
    # Guards against the login-success-then-404 regression observed in production.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    page = (root / "dashboard.html").read_text(encoding="utf-8")
    server = (root / "cloud_server.py").read_text(encoding="utf-8")
    assert "req('/auth/session')" in page
    assert 'Route("/auth/session", dashboard.session' in server
    assert 'Route("/api/console/session", dashboard.session' in server
    app = Starlette(routes=[
        Route("/auth/login",dashboard.login,methods=["POST"]),
        Route("/auth/session",dashboard.session,methods=["GET"]),
        Route("/api/console/session",dashboard.session,methods=["GET"]),
    ])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        assert c.get("/auth/session").json() == {"loggedIn":False}
        assert c.post("/auth/login",json={"password":"test-owner-password-is-secure"}).status_code==200
        assert c.get("/auth/session").json() == {"loggedIn":True}
        assert c.get("/api/console/session").json() == {"loggedIn":True}


def test_cleanup_deletes_only_orphaned_failed_hosted_media(working):
    from autoclips.settings import home
    first="prj_failed_vidiq"
    second="prj_good_vidiq"
    a=home()/"projects"/first
    b=home()/"projects"/second
    a.mkdir(parents=True); b.mkdir(parents=True)
    (a/"source.mp4").write_bytes(b"failed-video-copy")
    (b/"source.mp4").write_bytes(b"ready-video-copy")
    with db.conn() as c:
        for ident,path,status in ((first,a,"transcription_failed"),(second,b,"ready")):
            c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (ident,"hosted","https://storage.googleapis.com/review/test.mp4",
                       "Test",str(path/"source.mp4"),None,60,status,None,db.now()))
    assert dashboard._prune_failed_hosted_imports() == len(b"failed-video-copy")
    assert not (a/"source.mp4").exists()
    assert (b/"source.mp4").exists()


def test_approved_vidiq_manifest_queues_only_review_sources(working,monkeypatch):
    import json
    manifest=[{
       "video_id":"a036QoSqS4w",
       "title":"Cariani — história emocionante",
       "media_url":"https://storage.googleapis.com/vidiq-user-videos/testing/clip.mp4?Expires=1"
    }]
    monkeypatch.setenv("AUTOCLIPS_VIDIQ_REVIEW_BATCH",json.dumps(manifest))
    dashboard._db_init()
    dashboard._db_init()
    with db.conn() as c:
        rows=c.execute("SELECT id,source_kind,status,title FROM dashboard_sources WHERE original_video_id=?",
                       ("a036QoSqS4w",)).fetchall()
        assert len(rows)==1
        assert rows[0]["source_kind"]=="hosted"
        assert rows[0]["status"]=="queued"
        assert rows[0]["title"]=="Cariani — história emocionante"
        assert c.execute("SELECT count(*) FROM dashboard_publishes").fetchone()[0]==0


def test_like_cannot_publish_without_separate_rights_confirmation(working):
    import json
    clip=add_clip(working,989)
    app=Starlette(routes=[
        Route("/auth/login",dashboard.login,methods=["POST"]),
        Route("/api/console/review",dashboard.review,methods=["POST"])
    ])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        response=c.post("/api/console/review",json={"clip_id":clip,"decision":"like"},
                        headers={"X-Autoclips-Action":"1"})
        assert response.status_code==403
    with db.conn() as con:
        assert con.execute("SELECT count(*) FROM dashboard_publishes WHERE clip_id=?",(clip,)).fetchone()[0]==0


def test_source_authorization_required(working):
    app=Starlette(routes=[Route("/auth/login",dashboard.login,methods=["POST"]),
                           Route("/api/console/links",dashboard.add_links,methods=["POST"])])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        response=c.post("/api/console/links",json={"links":"https://youtu.be/q6OYTqiXmAw"},
                        headers={"X-AutoClips-Action":"1"})
        assert response.status_code==403


def test_original_source_upload_queues_real_autoclips_ingest(working):
    # A real MP4 from ffmpeg; upload requires private browser login and CSRF header.
    import subprocess
    from autoclips.settings import home
    original=working/"demo_original.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-f","lavfi","-i","color=c=blue:s=320x240:r=15",
                    "-t","11","-c:v","mpeg4",str(original)],check=True)
    assert original.stat().st_size>1024
    app=Starlette(routes=[
        Route("/auth/login",dashboard.login,methods=["POST"]),
        Route("/api/console/upload-source",dashboard.upload_source,methods=["POST"]),
    ])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        assert c.post("/api/console/upload-source",content=original.read_bytes(),
                      headers={"Content-Type":"video/mp4","X-Autoclips-Action":"1"}).status_code==401
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        assert c.post("/api/console/upload-source",content=original.read_bytes(),
                      headers={"Content-Type":"video/mp4"}).status_code==403
        response=c.post("/api/console/upload-source",content=original.read_bytes(),
                        headers={"Content-Type":"video/mp4","X-Autoclips-Action":"1"})
        assert response.status_code==201, response.text
        value=response.json()
        with db.conn() as sql:
            row=sql.execute("SELECT source_kind,status,link FROM dashboard_sources WHERE id=?",
                            (value["id"],)).fetchone()
        assert row["source_kind"]=="file" and row["status"]=="queued"
        assert (home()/"imports"/row["link"]).exists()


def test_video_file_stays_private_without_dashboard_cookie(working):
    clip=add_clip(working,1234)
    app=Starlette(routes=[Route("/api/console/media/{clip_id}",dashboard.media,methods=["GET"]),
                          Route("/auth/login",dashboard.login,methods=["POST"])])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        assert c.get("/api/console/media/"+clip).status_code==401
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        assert c.get("/api/console/media/"+clip).status_code==200


def test_agent_chat_media_ingests_once_and_never_publishes_without_rights(working, monkeypatch):
    import json
    entry = {
        "video_id": "Er5L6cxnRTc",
        "youtube_url": "https://www.youtube.com/watch?v=Er5L6cxnRTc",
        "media_url": "https://storage.googleapis.com/vidiq-user-videos/safe.mp4?sig=short",
        "title": "NASA JPL short",
        "private_publish_approved": True,
        "rights_confirmed": False,
    }
    monkeypatch.setenv("AUTOCLIPS_AGENT_CHAT_IMPORT", json.dumps(entry))
    dashboard._db_init()
    dashboard._db_init()  # must never enqueue same signed link twice
    with db.conn() as c:
        rows = c.execute("SELECT * FROM dashboard_sources WHERE id='src_chat_Er5L6cxnRTc'").fetchall()
        assert len(rows) == 1
        rights = c.execute("SELECT * FROM chat_ingest_permissions WHERE source_id=?",
                           ("src_chat_Er5L6cxnRTc",)).fetchone()
        assert rights["private_publish_approved"] == 1
        assert rights["rights_confirmed"] == 0
        clip = add_clip(working, 990)
        c.execute("""UPDATE dashboard_sources SET status='awaiting_review', project_id=?
                     WHERE id='src_chat_Er5L6cxnRTc'""", ("prj_000000000990",))
    dashboard._queue_one_approved_chat_source()
    assert publish_queue.get_publication(clip) is None
    with db.conn() as c:
        c.execute("UPDATE chat_ingest_permissions SET rights_confirmed=1 WHERE source_id=?",
                  ("src_chat_Er5L6cxnRTc",))
    # A rights flag alone does not bypass the Portuguese captions/photo QA.
    dashboard._queue_one_approved_chat_source()
    assert publish_queue.get_publication(clip) is None
    qa = {"language":"pt","image_mode":"owner_provided",
          "caption_events":40,"auto_publish_ready":True}
    import json
    (working/"imports"/(clip+".qa.json")).write_text(json.dumps(qa))
    dashboard._queue_one_approved_chat_source()
    row = publish_queue.get_publication(clip)
    assert row["status"] == "queued" and row["privacy"] == "private"
    dashboard._queue_one_approved_chat_source()
    assert publish_queue.get_publication(clip)["status"] == "queued"

def test_completed_english_import_is_rejected_before_rendering(working, monkeypatch):
    source_id="src_english_quality_gate"
    project_id="prj_english_quality_gate"
    transcript=working/"projects"/project_id/"transcript.json"
    transcript.parent.mkdir(parents=True,exist_ok=True)
    import json
    transcript.write_text(json.dumps({
        "language":"en",
        "segments":[{"start":float(i*4),"end":float((i+1)*4),
                     "text":"This is a long English sentence about a surprising story."} for i in range(15)],
        "words":[]}))
    with db.conn() as c:
        c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (project_id,"file","source.mp4","English original",
                  str(transcript.parent/"source.mp4"),str(transcript),60,"ready",None,db.now()))
        c.execute("""INSERT INTO dashboard_sources
                     (id,link,source_kind,status,project_id,job_id,created_at,updated_at)
                     VALUES (?,?,'file','importing',?,?,?,?)""",
                  (source_id,"source.mp4",project_id,"job_english",db.now(),db.now()))
    monkeypatch.setattr(pipeline,"job_status",lambda *_: {"status":"completed"})
    monkeypatch.setattr(dashboard,"_queue_one_nasa_private_validation",lambda:None)
    monkeypatch.setattr(dashboard,"_queue_one_approved_chat_source",lambda:None)
    monkeypatch.setattr(dashboard,"publish_next",lambda:None)
    dashboard._tick()
    with db.conn() as c:
        state=c.execute("SELECT status,error FROM dashboard_sources WHERE id=?",(source_id,)).fetchone()
        assert state["status"]=="failed"
        assert "português" in state["error"]
        assert c.execute("SELECT count(*) FROM clips WHERE project_id=?",(project_id,)).fetchone()[0]==0
