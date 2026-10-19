from autoclips import pipeline
import pytest

def test_hosted_approved_enqueued_for_download(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    jobs=[]
    def stub_submit(kind,target,fn,*args):
        jobs.append((kind,target,fn,args))
        return 'job_demo'
    monkeypatch.setattr(pipeline,'_submit',stub_submit)
    r=pipeline.new_project('https://storage.googleapis.com/bucket/video.mp4?sig=abc',source_kind='hosted',authorized=True,auto_transcribe=False)
    assert r['job_id']=='job_demo'
    assert jobs[0][0]=='ingest'
    assert jobs[0][3][2]=='hosted'

def test_hosted_unapproved_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with pytest.raises(PermissionError):
        pipeline.new_project('https://storage.googleapis.com/bucket/video.mp4',source_kind='hosted',authorized=False)

def test_http_bridge_queues_hosted_source(tmp_path,monkeypatch):
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from autoclips.api_http import create_project
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    monkeypatch.setattr(pipeline,'_submit',lambda *args: 'job_demo')
    with TestClient(Starlette(routes=[Route('/api/projects',create_project,methods=['POST'])])) as c:
        resp=c.post('/api/projects',json={'source':'https://storage.googleapis.com/bucket/video.mp4?sig=abc','source_kind':'hosted','authorized':True,'auto_transcribe':False})
    assert resp.status_code==202
