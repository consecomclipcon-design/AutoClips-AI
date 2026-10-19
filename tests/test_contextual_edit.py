from pathlib import Path
import pytest
from autoclips import split_renderer as r


def test_layout_has_full_bleed_photo_no_blank_band():
    f = r.build_filters('captions.ass', size=(1080, 1920))
    assert 'overlay=0:1094' in f
    assert 'pad=1080:1920' in f
    assert 'scale=1080:826' in f
    assert 'scale=1080:1094' in f


def test_strong_hook_and_spoken_captions_separate(tmp_path):
    ass=tmp_path/'clip.ass'
    r.write_editorial_captions(
        [{'start':0,'end':3,'text':'Meus amigos fizeram uma aposta'}],
        0, 42, ass,
        hook_white='APOSTARAM QUE ELE', hook_red='NAO IA CASAR!')
    text=ass.read_text()
    assert 'Style: HookWhite' in text and 'Style: HookRed' in text
    assert 'Style: Spoken' in text
    assert 'APOSTARAM QUE ELE' in text and 'NAO IA CASAR!' in text
    assert r'\pos(540,810)' in text
    assert r'\pos(540,1040)' in text
    assert r'\pos(540,1130)' in text


def test_contextual_clip_min_duration_and_independent_payoff():
    from autoclips.context import contextual_window
    timeline=[{'start':0,'end':12,'text':'Apresentação.'},
              {'start':12,'end':28,'text':'Amigos apostaram.'},
              {'start':28,'end':47,'text':'Ele explicou o motivo.'},
              {'start':47,'end':68,'text':'Contou o dia do casamento.'},
              {'start':68,'end':83,'text':'Confirmação final.'}]
    result=contextual_window(timeline, anchor_start=29, anchor_end=37, min_seconds=35, max_seconds=85)
    assert result['start'] <= 12
    assert result['end'] >= 47
    assert result['end']-result['start'] >=35
    assert result['end']-result['start'] <=85


def test_contextual_clip_respects_three_minute_limit():
    from autoclips.context import contextual_window
    with pytest.raises(ValueError):
        contextual_window([{'start':0,'end':400,'text':'v'}],0,60,max_seconds=200)

@pytest.mark.skipif(__import__('shutil').which('ffmpeg') is None, reason='ffmpeg missing')
def test_real_media_render_with_hook_preserves_audio_and_lower_image(tmp_path):
    import subprocess, json
    src=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','testsrc2=s=640x360:r=15:d=2',
                    '-f','lavfi','-i','sine=frequency=300:duration=2',
                    '-c:v','mpeg4','-c:a','aac','-shortest',str(src)],check=True)
    photo=tmp_path/'photo.jpg'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','color=blue:s=320x240',
                    '-frames:v','1',str(photo)],check=True)
    target=tmp_path/'final.mp4'
    result=r.render_split(source=src,image=photo,words=[{'start':.1,'end':1.8,'text':'Apostaram que ele nao casaria'}],
                          start=0,end=1.9,output=target,size=(540,960),
                          hook_white='APOSTARAM QUE ELE',hook_red='NAO IA CASAR!')
    assert target.stat().st_size>30000
    assert result['caption_events']==1
    assert 'HookWhite' in target.with_suffix('.ass').read_text()
    meta=json.loads(subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height',
                                    '-of','json',str(target)],text=True,capture_output=True,check=True).stdout)
    assert any(st.get('codec_type')=='audio' for st in meta['streams'])
    assert any(st.get('width')==540 and st.get('height')==960 for st in meta['streams'])
