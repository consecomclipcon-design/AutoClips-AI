import os
from pathlib import Path
import pytest

from autoclips.transcript import parse_srt, save_transcript, load_transcript
from autoclips.media import is_youtube_link, import_local
from autoclips.ranking import suggest
from autoclips.renderer import ass_time, escape_ass, captions_ass
from autoclips.settings import home
from autoclips import database as db


def test_link_host_security():
    assert is_youtube_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_link("https://youtu.be/dQw4w9WgXcQ")
    assert not is_youtube_link("https://youtube.com.bad.example/watch?v=x")
    assert not is_youtube_link("file:///etc/passwd")
    assert not is_youtube_link("http://youtube.com/watch?v=x")


def test_srt_parser():
    data = """1
00:00:01,000 --> 00:00:03,000
Olá pessoal!

2
00:00:04,000 --> 00:00:05,500
Tudo bem?
"""
    segments = parse_srt(data)
    assert len(segments) == 2
    assert segments[0] == {"start": 1.0, "end": 3.0, "text": "Olá pessoal!"}
    assert segments[1]["end"] == 5.5


def test_ass_captions(tmp_path):
    path = tmp_path / "caption.ass"
    words = [{"start": 0.1, "end": 0.4, "text": "Olá"},
             {"start": 0.4, "end": 0.9, "text": "mundo!"}]
    assert captions_ass(words, 0, 1, path) == 2
    assert "Olá" in path.read_text()
    assert ass_time(1.2) == "0:00:01.20"
    assert escape_ass("{abc}") == r"\{abc\}"


def test_suggestions():
    segments = [{"start": i * 6, "end": (i + 1) * 6,
                 "text": ("Você sabia que ninguém conta esse segredo? " if i == 2 else "Um fato importante. ")}
                for i in range(12)]
    got = suggest(segments, 72, 2, 15, 35)
    assert 1 <= len(got) <= 2
    assert all(15 <= r["end"] - r["start"] <= 35 for r in got)


def test_local_import_restricts_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    home()
    with pytest.raises(ValueError):
        import_local("../../etc/passwd", "prj_invalid")


def test_approval_is_single_use(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    db.init_db()
    approval = db.reserve_approval("clip_any", "Título", "Desc", "private", False, None, "channel_test")
    assert db.consume_approval(approval["approval_token"])["title"] == "Título"
    with pytest.raises(ValueError):
        db.consume_approval(approval["approval_token"])
