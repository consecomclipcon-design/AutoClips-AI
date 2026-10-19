from pathlib import Path
import shutil
import subprocess
import pytest
from autoclips.renderer import render
from autoclips.media import probe


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg ausente')
def test_ffmpeg_render_one_second(tmp_path):
    src = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=black:s=160x90:r=15:d=1.5',
                    '-f','lavfi','-i','sine=frequency=440:duration=1.5',
                    '-c:v','mpeg4','-c:a','aac','-shortest',str(src)], check=True)
    words = [{'start':.1,'end':.5,'text':'Olá'},{'start':.5,'end':1,'text':'mundo'}]
    out = tmp_path / 'short.mp4'
    render(str(src), words, 0, 1.2, out, 'viral')
    assert out.is_file() and out.stat().st_size > 0
    info = probe(out)
    assert info['width'] == 1080
    assert info['height'] == 1920
    assert 1 <= info['duration'] <= 1.5
