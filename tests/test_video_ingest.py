import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock
import pytest

from autoclips.media import is_youtube_link, import_youtube_approved

@pytest.mark.parametrize('url',["https://youtube.com/playlist?list=PL123", "https://youtube.com/watch?v=abc&list=PL123", "https://youtu.be/", "https://www.youtube.com/watch?v=", "https://youtu.be/abcdef?list=xyz"])
def test_youtube_rejects_playlist_and_invalid_video(url):
    assert not is_youtube_link(url)


def test_youtube_requires_explicit_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    monkeypatch.setenv("ALLOW_YOUTUBE_IMPORT", "true")
    with pytest.raises(PermissionError):
        import_youtube_approved("https://www.youtube.com/watch?v=q6OYTqiXmAw", "p1", False)


def test_downloader_uses_safe_single_video_options_and_atomic_output(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    monkeypatch.setenv("ALLOW_YOUTUBE_IMPORT", "true")
    calls = []

    class FakeDownloader:
        def __init__(self, options): self.options=options
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def extract_info(self, url, download=False):
            calls.append(("info",url,download))
            return {"id":"q6OYTqiXmAw", "duration":362, "_type":"video", "title":"Renato e Tati"}
        def download(self, urls):
            calls.append(("download",urls))
            output=Path(self.options['outtmpl'].replace('%(ext)s','mp4'))
            output.write_bytes(b"sample mp4 bytes")
            return 0

    def create(options):
        calls.append(("options",options))
        return FakeDownloader(options)
    monkeypatch.setitem(sys.modules,'yt_dlp',types.SimpleNamespace(YoutubeDL=create))
    output=import_youtube_approved('https://www.youtube.com/watch?v=q6OYTqiXmAw','p1',True)
    opts=next(c[1] for c in calls if c[0]=='options')
    assert output.name == 'source.mp4' and output.exists()
    assert opts['noplaylist'] is True and opts['socket_timeout'] <= 30
    assert opts['max_filesize'] < 500*1024*1024
    assert opts['js_runtimes'].get('node') is not None
    assert not (tmp_path/'projects'/'p1'/'source.part.mp4').exists()


def test_downloader_rejects_overlong_video_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    monkeypatch.setenv("ALLOW_YOUTUBE_IMPORT", "true")
    class FakeDownloader:
        def __init__(self,options): self.opts=options
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def extract_info(self, *_args,**_kwargs):
            return {"duration":99999,"_type":"video"}
        def download(self, _):
            pytest.fail('must reject before downloading')
    monkeypatch.setitem(sys.modules,'yt_dlp',types.SimpleNamespace(YoutubeDL=FakeDownloader))
    with pytest.raises(ValueError,match='Duração'):
        import_youtube_approved('https://youtu.be/q6OYTqiXmAw','p1',True)


def test_youtube_url_source_is_only_id_and_https():
    assert is_youtube_link('https://youtu.be/q6OYTqiXmAw')
    assert not is_youtube_link('https://www.youtube.com/redirect?q=https://example.com')
    assert not is_youtube_link('https://youtube.com/watch?v=a#evil')


def test_import_moves_uploaded_media_instead_of_duplicate_on_volume(tmp_path, monkeypatch):
    from autoclips.media import import_local
    from autoclips.settings import home
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    file=home()/'imports'/'upload_test.mp4'
    file.write_bytes(b'actual-mp4-placeholder')
    saved=import_local(file.name,'prj_test_01')
    assert saved.exists()
    assert saved.read_bytes()==b'actual-mp4-placeholder'
    assert not file.exists()


def test_youtube_large_source_chooses_small_format_without_manual_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    monkeypatch.setenv("ALLOW_YOUTUBE_IMPORT", "true")
    monkeypatch.setenv("AUTOCLIPS_POT_PROVIDER_URL", "http://autoclips-pot-provider.railway.internal:4416")
    calls = []

    class FakeDL:
        def __init__(self,options):
            self.params=options
            calls.append((options["extractor_args"]["youtube"]["player_client"][0],options))
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def extract_info(self,*a,**kw):
            if self.params["extractor_args"]["youtube"]["player_client"]==["mweb"]:
                raise RuntimeError("Sign in to confirm you're not a bot")
            return {"duration":90*60,"_type":"video","filesize":1006*1024*1024,
                    "formats":[{"format_id":"18","filesize_approx":120*1024*1024,
                                "height":360}]}
        def download(self, urls):
            out = Path(self.params["outtmpl"].replace("%(ext)s", "mp4"))
            out.write_bytes(b"small_enough_progressive_video")
            return 0

    monkeypatch.setitem(sys.modules,"yt_dlp",types.SimpleNamespace(YoutubeDL=FakeDL))
    output=import_youtube_approved("https://youtu.be/NmjiNtvSkFk","p_long_01",True)
    assert output.exists()
    assert [n for n,_ in calls]==["mweb","tv"]
    assert "height<=?360" in calls[-1][1]["format"]
    assert calls[0][1]["extractor_args"]["youtubepot-bgutilhttp"]["base_url"]==[
        "http://autoclips-pot-provider.railway.internal:4416"]


def test_youtube_provider_rejects_untrusted_address(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_POT_PROVIDER_URL","http://127.0.0.1:4416")
    from autoclips.media import _safe_pot_provider
    with pytest.raises(RuntimeError):
        _safe_pot_provider()


def test_youtube_strategy_selection_rejects_unknown_player(tmp_path,monkeypatch):
    from autoclips.media import _youtube_options
    with pytest.raises(ValueError):
        _youtube_options(tmp_path,"arbitrary-client",None)
