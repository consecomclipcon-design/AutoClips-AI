from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def client():
    from autoclips.api_http import create_project, status_job
    return TestClient(Starlette(routes=[Route('/api/projects',create_project,methods=['POST']),Route('/api/jobs/{job_id}',status_job,methods=['GET'])]))


def test_http_api_rejects_missing_authorization_for_youtube(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with client() as c:
        r=c.post('/api/projects',json={'source':'https://www.youtube.com/watch?v=q6OYTqiXmAw','source_kind':'youtube','authorized':False})
    assert r.status_code==403


def test_http_api_rejects_invalid_source(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with client() as c:
        r=c.post('/api/projects',json={'source':'http://127.0.0.1/admin','source_kind':'youtube','authorized':True})
    assert r.status_code==400


def test_http_api_enqueues_video_file_and_can_query_status(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    from autoclips.settings import home
    f=home()/'imports'/'clip.mp4'
    f.write_bytes(b'video')
    with client() as c:
        r=c.post('/api/projects',json={'source':'clip.mp4','source_kind':'file','authorized':True,'auto_transcribe':False})
        assert r.status_code==202
        job=r.json()['job_id']
        r2=c.get('/api/jobs/'+job)
        assert r2.status_code==200
        assert r2.json()['status'] in {'queued','running','completed','failed'}


def test_api_rejects_oversized_json_payload(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with client() as c:
        r=c.post('/api/projects',content='x'*9000,headers={'content-type':'application/json'})
    assert r.status_code in {400,413}
