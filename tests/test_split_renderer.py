"""Iterative acceptance tests for AutoClips split-screen v0.4."""
from pathlib import Path
import subprocess
import json
import shutil
import pytest

from autoclips import split_renderer as s


def test_01_limits_reject_over_three_minutes():
    with pytest.raises(ValueError): s.validate_window(10, 190.1)


def test_02_limits_reject_backward_window():
    with pytest.raises(ValueError): s.validate_window(50, 49)


def test_03_focal_clamped():
    assert s.clamp_focal(-3) == 0
    assert s.clamp_focal(3) == 1
    assert s.clamp_focal(.33) == pytest.approx(.33)


def test_04_reject_untrusted_media_paths(tmp_path):
    with pytest.raises(FileNotFoundError): s.validate_media(tmp_path / 'missing.mp4')


def test_05_bottom_image_requires_real_file(tmp_path):
    with pytest.raises(FileNotFoundError): s.validate_media(tmp_path / 'nonexistent.png')


def test_06_caption_text_stays_in_middle(tmp_path):
    ass = tmp_path / 'middle.ass'
    s.write_middle_captions([{'start': 0, 'end': 1, 'text': 'Olá mundo'}],0,1,ass)
    content=ass.read_text()
    assert 'Alignment' in content and 'Style: Main' in content
    assert 'Dialogue:' in content and 'Olá' in content
    assert r'\pos(540,960)' in content


def test_07_split_filter_contains_two_panels():
    f = s.build_filters('still.png', focal_x=.8)
    assert 'scale=' in f and 'overlay' in f and 'ass=' in f
    assert '960' in f


def test_08_attribution_is_sanitized():
    assert s.safe_credit('Fonte: vídeo\nOutra linha') == 'Fonte: vídeo Outra linha'
    assert len(s.safe_credit('x'*300)) <= 100


@pytest.fixture
def sample_video(tmp_path):
    movie=tmp_path/'landscape.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','color=c=gray:s=640x360:r=15:d=3',
                    '-f','lavfi','-i','sine=frequency=250:duration=3',
                    '-c:v','mpeg4','-c:a','aac','-shortest',str(movie)],check=True)
    return movie


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg ausente')
def test_09_render_split_9by16_preserves_audio(sample_video,tmp_path):
    image=tmp_path/'related.png'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','color=c=blue:s=640x360','-frames:v','1',str(image)],check=True)
    out=tmp_path/'clip.mp4'
    result=s.render_split(source=sample_video,image=image,words=[{'start':.2,'end':2.5,'text':'Olá mundo uma legenda boa'}],
                          start=0,end=2.8,output=out,credit='Teste CC BY 4.0',size=(540,960))
    meta=subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height,codec_type','-of','json',str(out)],capture_output=True,text=True,check=True)
    streams=json.loads(meta.stdout)['streams']
    assert any(x.get('width')==540 and x.get('height')==960 for x in streams)
    assert any(x.get('codec_type')=='audio' for x in streams)
    assert result['duration'] <= 180


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg ausente')
def test_10_fallback_lower_panel_frame(sample_video,tmp_path):
    out=tmp_path/'fallback.mp4'
    result=s.render_split(source=sample_video,image=None,words=[{'start':.1,'end':2.3,'text':'Isso vai funcionar'}],
                          start=0,end=2.5,output=out,size=(540,960))
    assert out.exists() and out.stat().st_size>10000
    assert result['image_mode']=='source_frame'
