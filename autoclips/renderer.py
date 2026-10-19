from __future__ import annotations
import math
import re
import subprocess
from pathlib import Path

STYLES = {
    "viral": ("&H0000FFFF", "&H00FFFFFF", 74),  # destaque amarelo BGR e branco
    "clean": ("&H00FFFFFF", "&H00FFFFFF", 60),
    "bold": ("&H0000FF00", "&H00FFFFFF", 80),
}


def ass_time(seconds: float) -> str:
    c = max(0, round(seconds * 100))
    return f"{c // 360000}:{(c // 6000) % 60:02d}:{(c // 100) % 60:02d}.{c % 100:02d}"


def escape_ass(s: str) -> str:
    return s.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", " ")


def _expand_subtitle_blocks(words: list[dict]) -> list[dict]:
    """Divide frases SRT em palavras. Tempos são ESTIMADOS, não alinhados pelo áudio."""
    result = []
    for item in words:
        tokens = item["text"].split()
        if not tokens:
            continue
        if len(tokens) == 1:
            result.append(item)
            continue
        weight = sum(max(len(t), 1) for t in tokens)
        duration = max(0.05, float(item["end"]) - float(item["start"]))
        cursor = float(item["start"])
        for token in tokens:
            span = duration * max(len(token), 1) / weight
            result.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "text": token})
            cursor += span
    return result


def captions_ass(words: list[dict], start: float, end: float, path: Path,
                 style: str = "viral") -> int:
    if style not in STYLES:
        raise ValueError("Estilo: viral, clean ou bold")
    highlight, white, size = STYLES[style]
    words = _expand_subtitle_blocks([w for w in words if w["end"] > start and w["start"] < end and w["text"].strip()])
    if not words:
        raise ValueError("Esse intervalo não tem texto para legendar")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,65,65,370,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    # Exibe 3 a 5 palavras e destaca a que está sendo dita.
    for g in range(0, len(words), 4):
        group = words[g:g + 4]
        for i, w in enumerate(group):
            t0 = max(start, w["start"])
            t1 = min(end, max(t0 + 0.07, w["end"]))
            if i + 1 < len(group):
                t1 = min(t1, group[i + 1]["start"])
            if t1 <= t0:
                continue
            parts = []
            for k, word in enumerate(group):
                col = highlight if k == i else white
                parts.append("{" + r"\c" + col + "}" + escape_ass(word["text"]))
            if sum(len(w["text"]) for w in group) + len(group) - 1 > 23 and len(group) > 2:
                line = " ".join(parts[:2]) + r"\N" + " ".join(parts[2:])
            else:
                line = " ".join(parts)
            events.append(f"Dialogue: 0,{ass_time(t0-start)},{ass_time(t1-start)},Main,,0,0,0,,{line}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return len(events)


def render(source_path: str, words: list[dict], start: float, end: float,
           output_path: Path, style: str = "viral") -> dict:
    if end <= start or end - start > 180 or start < 0:
        raise ValueError("Corte precisa ter entre 0 e 180 segundos de duração")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_file = output_path.with_suffix(".ass")
    events = captions_ass(words, start, end, ass_file, style)
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920,ass=" + ass_file.name)
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start),
            "-i", str(source_path), "-t", str(end-start),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart", str(output_path)]
    subprocess.run(args, cwd=str(output_path.parent), check=True, capture_output=True, text=True)
    return {"file": str(output_path), "seconds": round(end-start, 2),
            "caption_events": events, "layout": "9:16", "dimensions": "1080x1920"}
