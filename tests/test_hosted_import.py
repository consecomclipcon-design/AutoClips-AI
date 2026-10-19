import pytest
from unittest.mock import patch
from autoclips.media import import_hosted_approved

class FakeResponse:
    status=200
    def __init__(self,data,size=None):
        self.data=data; self.offset=0
        self.headers={'Content-Type':'video/mp4','Content-Length':str(size if size is not None else len(data))}
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self,n):
        chunk=self.data[self.offset:self.offset+n]
        self.offset+=len(chunk)
        return chunk

class FakeOpener:
    def __init__(self,data,size=None): self.data=data;self.size=size
    def open(self,request,timeout): return FakeResponse(self.data,self.size)

URL='https://storage.googleapis.com/authorized/example.mp4?token=temporary'

def test_download_hosted_authorized(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with patch('urllib.request.build_opener',return_value=FakeOpener(b'0000ftypvideodata0012345')):
        output=import_hosted_approved(URL,'test_video',True)
    assert output.read_bytes().startswith(b'0000ftyp')
    assert output.name=='source.mp4'

def test_download_hosted_rejects_unapproved_and_private(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with pytest.raises(PermissionError): import_hosted_approved(URL,'p',False)
    for u in ('http://storage.googleapis.com/a.mp4','https://127.0.0.1/a.mp4','https://storage.googleapis.com.evil.com/a.mp4'):
        with pytest.raises(ValueError): import_hosted_approved(u,'p',True)

def test_download_hosted_rejects_large_without_partial(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    with patch('urllib.request.build_opener',return_value=FakeOpener(b'12345',size=190*1024*1024)):
        with pytest.raises(ValueError): import_hosted_approved(URL,'p',True)
    assert not list(tmp_path.rglob('*.part'))
