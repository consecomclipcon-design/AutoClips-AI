"""Local pipeline smoke test: original file -> SRT -> split MP4; no online claims."""
import json
import shutil
import subprocess
import time
import pytest
from autoclips import database as db
from autoclips import pipeline
from autoclips.settings import home


def wait(job_id, timeout=25):
    stop=time.time()+timeout
    while time.time()<stop:
        j=pipeline.job_status(job_id)
        if j['status']=='completed':return j
        if j['status']=='failed':pytest.fail(str(j['error']))
        time.sleep(.15)
    pytest.fail('Job timeout: '+job_id)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg unavailable')
def test_full_local_split_workflow(tmp_path,monkeypatch):
    monkeypatch.setenv('AUTOCLIPS_HOME',str(tmp_path))
    home(); db.init_db()
    source=tmp_path/'imports'/'original.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','testsrc=size=640x360:rate=15:duration=3',
                    '-f','lavfi','-i','sine=frequency=400:duration=3',
                    '-c:v','mpeg4','-c:a','aac','-shortest',str(source)],check=True)
    (tmp_path/'imports'/'sub.srt').write_text('1\n00:00:00,200 --> 00:00:02,600\nUma entrevista interessante.\n',encoding='utf-8')
    p=pipeline.new_project('original.mp4','file',auto_transcribe=False)
    wait(p['job_id'])
    t=pipeline.start_transcription(p['project_id'],'sub.srt')
    wait(t['job_id'])
    assert pipeline.read_transcript(p['project_id'])['segments'][0]['text']=='Uma entrevista interessante.'
    c=pipeline.start_render_split(p['project_id'],0,2.8)
    result=wait(c['job_id'])['result']
    assert result['layout']=='top_video_bottom_image'
    assert result['image_mode']=='source_frame'
    clip=db.one('clips',c['clip_id'])
    assert clip['status']=='ready'
    meta=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height','-of','json',clip['path']],text=True,capture_output=True,check=True)
    streams=json.loads(meta.stdout)['streams']
    assert any(s.get('width')==1080 and s.get('height')==1920 for s in streams)
    assert any(s.get('codec_type')=='audio' for s in streams)
