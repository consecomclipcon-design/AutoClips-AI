"""Regression tests for owner dashboard and 20/day public publishing queue."""
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


def test_public_approval_requires_explicit_consent(working):
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
        assert privacy=="public" and channel_id=="UC"+"x"*22
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


def test_source_authorization_required(working):
    app=Starlette(routes=[Route("/auth/login",dashboard.login,methods=["POST"]),
                           Route("/api/console/links",dashboard.add_links,methods=["POST"])])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        response=c.post("/api/console/links",json={"links":"https://youtu.be/q6OYTqiXmAw"},
                        headers={"X-AutoClips-Action":"1"})
        assert response.status_code==403


def test_video_file_stays_private_without_dashboard_cookie(working):
    clip=add_clip(working,1234)
    app=Starlette(routes=[Route("/api/console/media/{clip_id}",dashboard.media,methods=["GET"]),
                          Route("/auth/login",dashboard.login,methods=["POST"])])
    with TestClient(app,base_url="https://autoclips-worker-production.up.railway.app") as c:
        assert c.get("/api/console/media/"+clip).status_code==401
        c.post("/auth/login",json={"password":"test-owner-password-is-secure"})
        assert c.get("/api/console/media/"+clip).status_code==200
