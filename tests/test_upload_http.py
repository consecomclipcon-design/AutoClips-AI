import asyncio
import hashlib
import os
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def make_client():
    from autoclips.upload_http import upload_media
    return TestClient(Starlette(routes=[Route('/api/uploads',upload_media,methods=['PUT'])]))


def test_upload_streams_original_file_to_import_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    sample=b'video-media-test-contents'
    with make_client() as c:
        res=c.put('/api/uploads',data=sample,headers={'x-filename':'recording.mp4','content-type':'video/mp4'})
    assert res.status_code==201
    data=res.json()
    assert data['sha256']==hashlib.sha256(sample).hexdigest()
    assert data['bytes']==len(sample)
    assert data['filename'].endswith('.mp4')
    assert (tmp_path/'imports'/data['filename']).read_bytes()==sample


def test_upload_rejects_traversal_and_nonvideo(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with make_client() as c:
        res=c.put('/api/uploads',data=b'x',headers={'x-filename':'../../evil.mp4','content-type':'video/mp4'})
        wrong=c.put('/api/uploads',data=b'x',headers={'x-filename':'evil.sh','content-type':'video/mp4'})
    assert res.status_code==400
    assert wrong.status_code==400
    assert not list((tmp_path/'imports').glob('*'))


def test_upload_rejects_declared_oversize_and_missing_name(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with make_client() as c:
        missing=c.put('/api/uploads',data=b'x',headers={'content-type':'application/octet-stream'})
        wrong=c.put('/api/uploads',data=b'x',headers={'x-filename':'ok.mov','content-type':'text/plain'})
    assert missing.status_code==400
    assert wrong.status_code==415


def test_upload_cleans_partial_data_when_size_exceeded(tmp_path, monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    monkeypatch.setenv('AUTOCLIPS_MAX_UPLOAD_BYTES','10')
    with make_client() as c:
        response=c.put('/api/uploads',data=b'a'*100,headers={'x-filename':'clip.mp4','content-type':'video/mp4'})
    assert response.status_code==413
    assert not list((tmp_path/'imports').glob('*'))
