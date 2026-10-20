"""AutoClips portrait split-screen renderer (top video + bottom related still).

Captions are drawn in the center divider, rather than obscuring faces.
If no verified, licensed image is supplied, a still is extracted from source.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from .renderer import captions_ass


def validate_window(start: float, end: float) -> None:
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end-start > 180:
        raise ValueError('A duração de cada corte deve ficar entre 0 e 180 segundos')


def clamp_focal(value: float) -> float:
    if not math.isfinite(float(value)):
        raise ValueError('Ponto focal inválido')
    return max(0., min(1., float(value)))


def validate_media(path: str | Path) -> Path:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f'Arquivo inexistente: {p.name}')
    return p


def safe_credit(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()[:100]


def write_middle_captions(words: list[dict], start: float, end: float, ass: Path) -> int:
    count = captions_ass(words, start, end, ass, style='viral')
    data = ass.read_text(encoding='utf-8')
    # PlayResX/Y 1080x1920; captions occupy the separate middle divider.
    lines = []
    for line in data.splitlines():
        if line.startswith('Dialogue: '):
            prefix, body = line.rsplit(',,', 1)
            line = prefix + ',,' + r'{\an5\pos(540,960)}' + body
        lines.append(line)
    data='\n'.join(lines)+'\n'
    data=data.replace('Style: Main,DejaVu Sans,74,', 'Style: Main,DejaVu Sans,58,')
    data=data.replace(',-1,0,0,0,100,100,0,0,1,5,1,2,65,65,370,1',
                      ',-1,0,0,0,100,100,0,0,1,5,1,5,65,65,0,1')
    ass.write_text(data,encoding='utf-8')
    return count


def build_filters(ass_name: str, focal_x: float = .5, size: tuple[int,int]=(540,960)) -> str:
    w,h=size
    if w<240 or h<400 or w%2 or h%2:
        raise ValueError('Tamanho inválido: largura/altura pares e suficientes')
    focal=clamp_focal(focal_x)
    # Give captions their own visible dark middle strip; they must not cover
    # either the speaker or the contextual bottom photo.
    top_h=round(h*.43)//2*2
    lower_start=round(h*.57)//2*2
    lower_h=h-lower_start
    # Instead of stretching images, crop to fill each panel around focal point.
    # The unpainted gap remains black, giving white/yellow captions contrast.
    top=(f'[0:v]scale={w}:{top_h}:force_original_aspect_ratio=increase,'
         f'crop={w}:{top_h}:x=(in_w-out_w)*{focal}:y=(in_h-out_h)/2,'
         f'pad={w}:{h}:0:0:black[top]')
    lower=(f'[1:v]scale={w}:{lower_h}:force_original_aspect_ratio=increase,'
           f'crop={w}:{lower_h}[bottom]')
    effect=(f'[top][bottom]overlay=0:{lower_start}:shortest=1,'
            f'ass={ass_name}[vout]')
    return ';'.join((top,lower,effect))


def _ass_safe(text: str) -> str:
    return re.sub(r'[{}\\]', '', text).replace('\n', ' ').strip()[:120]


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f'{cs//360000}:{(cs//6000)%60:02d}:{(cs//100)%60:02d}.{cs%100:02d}'


def write_editorial_captions(words: list[dict], start: float, end: float,
                              ass: Path, *, hook_white: str, hook_red: str) -> int:
    """Separates spoken captions above from the editorial white/red hook."""
    white, red = _ass_safe(hook_white), _ass_safe(hook_red)
    if not white or not red:
        raise ValueError('The editorial hook requires both white and red text')
    headers = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Spoken,DejaVu Sans,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,5,20,20,0,1
Style: HookWhite,DejaVu Sans,74,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,1,0,0,100,100,0,0,1,6,2,5,20,20,0,1
Style: HookRed,DejaVu Sans,82,&H003C23EF,&H000000FF,&H00000000,&H80000000,-1,1,0,0,100,100,0,0,1,6,2,5,20,20,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    duration = end - start
    lines = [headers]
    count = 0
    for w in words:
        a = max(0, float(w['start']) - start)
        b = min(duration, float(w['end']) - start)
        if b <= a: continue
        val = _ass_safe(str(w.get('text', '')))
        if not val: continue
        lines.append(f'Dialogue: 1,{_ass_time(a)},{_ass_time(b)},Spoken,,0,0,0,,{{\\an5\\pos(540,960)}}{val}\n')
        count += 1
    lines.append(f'Dialogue: 2,0:00:00.00,{_ass_time(duration)},HookWhite,,0,0,0,,{{\\an5\\pos(540,125)}}{white}\n')
    lines.append(f'Dialogue: 2,0:00:00.00,{_ass_time(duration)},HookRed,,0,0,0,,{{\\an5\\pos(540,215)}}{red}\n')
    ass.write_text(''.join(lines), encoding='utf-8')
    return count


def write_static_hook(ass: Path, start: float, end: float,
                      top: str, bottom: str) -> int:
    """One elegant, motionless, two-line caption for the ENTIRE video.

    There are no word-by-word highlights. The hook stays anchored in the
    dark central divider, clear of the real video and contextual photograph.
    """
    validate_window(start, end)
    top, bottom = _ass_safe(top).upper(), _ass_safe(bottom).upper()
    if not (6 <= len(top) <= 26 and 5 <= len(bottom) <= 26):
        raise ValueError("Gancho precisa ter duas linhas curtas e legíveis.")
    duration = _ass_time(end - start)
    content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HookTop,Lato,75,&H00FFFFFF,&H00FFFFFF,&H00140C0C,&H60000000,-1,0,0,0,100,100,0.5,0,1,5,1,5,26,26,0,1
Style: HookAccent,Lato,85,&H000000FF,&H000000FF,&H00140C0C,&H60000000,-1,0,0,0,100,100,0.3,0,1,6,1,5,24,24,0,1
Style: Underline,DejaVu Sans,10,&H00FF52EB,&H00FF52EB,&H00FF52EB,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Divider in PlayRes=1080x1920 lies between y=826 and 1094.
    # Fixed text at y=913 and y=1004 leaves generous clearance and
    # works for both HD (1080x1920) and half-size (540x960) rendering.
    content += (f'Dialogue: 2,0:00:00.00,{duration},HookTop,,0,0,0,,'
                f'{{\\an5\\pos(540,913)}}{top}\n')
    content += (f'Dialogue: 2,0:00:00.00,{duration},HookAccent,,0,0,0,,'
                f'{{\\an5\\pos(540,1004)}}{bottom}\n')
    content += (f'Dialogue: 1,0:00:00.00,{duration},Underline,,0,0,0,,'
                r'{\an7\pos(390,846)\p1\1c&H00FF52EB&}m 0 0 l 300 0 300 7 0 7' '\n')
    ass.write_text(content, encoding='utf-8')
    return 2


def render_split(*, source: str | Path, words: list[dict],start: float,end: float,
                 output: str | Path, image: str | Path | None = None,
                 focal_x: float=.5, credit: str='', size: tuple[int,int]=(540,960),
                 hook_white: str | None=None, hook_red: str | None=None,
                 static_hook: tuple[str,str] | None=None) -> dict:
    validate_window(start,end)
    src=validate_media(source)
    if image is not None:
        img=validate_media(image)
        mode='related_image'
    else:
        mode='source_frame'
    out=Path(output).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    ass=out.with_suffix('.ass')
    if static_hook is not None:
        count=write_static_hook(ass,start,end,static_hook[0],static_hook[1])
        caption_mode='static_hook'
    elif hook_white or hook_red:
        count=write_editorial_captions(words,start,end,ass,hook_white=hook_white or '',hook_red=hook_red or '')
        caption_mode='legacy_editorial'
    else:
        count=write_middle_captions(words,start,end,ass)
        caption_mode='spoken_captions'
    if credit:
        # Make Creative Commons attribution visible in the final MP4 itself,
        # not just in metadata that disappears on reposts.
        value = _ass_safe(safe_credit(credit))
        if value:
            current = ass.read_text(encoding='utf-8')
            style = ('Style: PhotoCredit,DejaVu Sans,26,&H00FFFFFF,&H000000FF,'
                     '&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,18,1\n')
            current = current.replace('[Events]',style+'[Events]',1)
            current += ('Dialogue: 2,0:00:00.00,'+_ass_time(end-start)+
                        ',PhotoCredit,,0,0,0,,'+
                        r'{\an2\pos(540,1870)}'+value+'\n')
            ass.write_text(current, encoding='utf-8')
    if image is None:
        img=out.with_name(out.stem+'_still.png')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                        '-ss',str(start),'-i',str(src),'-frames:v','1',str(img)],
                       capture_output=True,text=True,check=True)
    fc=build_filters(ass.name,focal_x,size)
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y',
         '-filter_complex_threads','1','-threads','1',
         '-ss',str(start),'-i',str(src),
         '-loop','1','-i',str(img),'-t',str(end-start),'-filter_complex',fc,
         '-map','[vout]','-map','0:a?','-c:v','libx264','-preset','ultrafast',
         '-threads','1','-crf','24',
         '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart','-shortest',str(out)]
    subprocess.run(cmd,cwd=str(out.parent),capture_output=True,text=True,check=True)
    return {'output':str(out),'duration':round(end-start,2),'dimensions':f'{size[0]}x{size[1]}',
            'layout':'top_video_middle_captions_bottom_image','image_mode':mode,'caption_events':count,
            'caption_strip':'center','caption_mode':caption_mode,
            'hook_text':(' '.join(static_hook) if static_hook else ''),
            'credit':safe_credit(credit)}
