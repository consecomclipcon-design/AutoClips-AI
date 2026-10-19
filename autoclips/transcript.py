from __future__ import annotations
import json
import re
from pathlib import Path


def _seconds(s: str) -> float:
    # 00:00:01,120 / 00:00:01.120
    match = re.fullmatch(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})", s.strip())
    if not match:
        raise ValueError(f"Timestamp SRT inválido: {s}")
    h, m, sec, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, '0')) / 1000


def parse_srt(content: str) -> list[dict]:
    """Importação de SRT como segmentos (precisão de legenda por frase)."""
    result = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing < 0:
            continue
        a, b = [x.strip().split(" ")[0] for x in lines[timing].split("-->", 1)]
        text = " ".join(re.sub(r"<[^>]+>", "", line).strip() for line in lines[timing + 1:]).strip()
        if text:
            result.append({"start": _seconds(a), "end": _seconds(b), "text": text})
    if not result:
        raise ValueError("SRT não contém falas válidas")
    return result


def transcribe(media_path: Path, *, srt_path: Path | None = None,
               model_name: str = "small", device: str = "cpu", compute_type: str = "int8") -> dict:
    if srt_path:
        segments = parse_srt(srt_path.read_text(encoding="utf-8-sig"))
        return {"source": "srt", "language": "und", "segments": segments,
                "words": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments]}
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper ausente; execute pip install -e . ou envie SRT") from exc
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(str(media_path), beam_size=5,
                                           word_timestamps=True, vad_filter=True)
    segments = []
    words = []
    for s in segments_iter:
        segments.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
        if s.words:
            for w in s.words:
                if w.start is None or w.end is None or not w.word.strip():
                    continue
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "text": w.word.strip()})
        else:
            words.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
    if not segments:
        raise ValueError("Não foram detectadas falas nesse vídeo")
    return {"source": "whisper", "language": info.language, "segments": segments, "words": words}


def save_transcript(project_id: str, result: dict, base_dir: Path) -> Path:
    path = base_dir / "projects" / project_id / "transcript.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_transcript(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
