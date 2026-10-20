"""Static hook captions: no invented claims, no word-by-word flicker."""
from pathlib import Path
import json
import shutil
import subprocess
import pytest

from autoclips.static_hook import generate_static_hook
from autoclips.split_renderer import write_static_hook, render_split


def segments(*texts):
    return [{"start":i*4.0,"end":(i+1)*4.0,"text":s}
            for i,s in enumerate(texts)]


def test_supplement_hook_grounded_in_spoken_content():
    result=generate_static_hook(
        "Qual suplemento tomar? Muzy responde",
        segments("Qual suplemento tomar? Vou explicar agora.",
                 "Tem creatina, whey e vitamina para considerar.",
                 "É importante ver cada caso."),
        0,12)
    assert result["top"]=="QUAL SUPLEMENTO"
    assert result["bottom"]=="VOCÊ DEVE TOMAR?"
    assert result["source"]=="subject_supported_by_speech"


def test_title_topic_without_spoken_evidence_never_invents_hook():
    result=generate_static_hook(
        "Qual suplemento tomar? Muzy responde",
        segments("Hoje eu estou falando sobre futebol e como treinar.",
                 "Uma bola rola no gramado durante a partida.",
                 "Estamos perto do encerramento dessa história."),
        0,12)
    assert not (result["top"] == "QUAL SUPLEMENTO" and
                result["bottom"] == "VOCÊ DEVE TOMAR?")


def test_olympia_hook_is_question_not_fake_revelation():
    result=generate_static_hook("Depois do Olympia: o que vem pela frente?",
        segments("Depois do Olympia tem outras competições.",
                 "O atleta explica quais são os próximos planos."),
        0,8)
    assert "OLYMPIA" in result["bottom"]
    assert result["bottom"].endswith("?")
    assert "REVELOU" not in result["top"] + result["bottom"]


def test_static_hook_has_only_full_video_events(tmp_path):
    ass=tmp_path/"hook.ass"
    count=write_static_hook(ass,13.2,53.2,"QUAL SUPLEMENTO","VOCÊ DEVE TOMAR?")
    content=ass.read_text(encoding="utf-8")
    assert count==2
    assert content.count("Dialogue:")==3  # two static text lines + accent stroke
    assert content.count("0:00:00.00,0:00:40.00")==3
    assert "Style: HookTop" in content and "Style: HookAccent" in content
    assert "Spoken" not in content and "Main," not in content
    assert r"\pos(540,913)" in content and r"\pos(540,1004)" in content


@pytest.mark.parametrize("top,bottom", [
    ("", "ASSISTA"),
    ("MUITO LONGA A PRIMEIRA FRASE QUE NAO CABE", "OK"),
    ("ASSISTA", "MUITO LONGA A SEGUNDA FRASE QUE NAO CABE")
])
def test_hook_rejects_unreadable_line_lengths(tmp_path,top,bottom):
    with pytest.raises(ValueError):
        write_static_hook(tmp_path/"a.ass",0,34,top,bottom)


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="FFmpeg ausente")
def test_static_hook_renders_mp4_with_audio_and_photo(tmp_path):
    sample=tmp_path/"source.mp4"
    photo=tmp_path/"photo.png"
    out=tmp_path/"result.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
       "-f","lavfi","-i","color=c=gray:s=640x360:r=15:d=3",
       "-f","lavfi","-i","sine=frequency=550:duration=3",
       "-c:v","mpeg4","-c:a","aac","-shortest",str(sample)],check=True)
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
       "-f","lavfi","-i","color=c=blue:s=640x360","-frames:v","1",
       str(photo)],check=True)
    result=render_split(source=sample,image=photo,words=[],start=0,end=2.8,
        output=out,static_hook=("QUAL SUPLEMENTO","VOCÊ DEVE TOMAR?"),
        size=(540,960))
    assert out.is_file() and out.stat().st_size > 10000
    assert result["caption_mode"]=="static_hook"
    assert result["caption_events"]==2
    meta=json.loads(subprocess.run(["ffprobe","-v","error",
         "-show_entries","stream=codec_type,width,height","-of","json",str(out)],
        check=True,capture_output=True,text=True).stdout)
    assert any(x.get("width")==540 and x.get("height")==960 for x in meta["streams"])
    assert any(x.get("codec_type")=="audio" for x in meta["streams"])
