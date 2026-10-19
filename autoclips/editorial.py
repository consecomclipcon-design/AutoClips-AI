"""Conservative Portuguese-only editorial gate for automatic AutoClips previews.

A ranking is not a factual claim about virality. Incomplete openings/endings
are rejected instead of publishing incoherent content automatically.
"""
from __future__ import annotations
import re
from .ranking import suggest

OPENERS = (
    "você sabia", "sabia que", "imagina", "olha só", "olha isso", "eu nunca",
    "nunca", "ninguém", "o segredo", "a verdade", "o problema", "o erro",
    "o pior", "o melhor", "sabe o que", "por que", "por quê", "como",
    "qual", "quem", "o que", "por isso", "não acredito",
    "aconteceu", "consegui", "descobri", "absurdo", "história", "incrível",
    "se você", "cê sabe",
)
BAD_ENDINGS = ("porque", "mas", "então", "quando", "se", "que", "e", "ou", "pra", "para")


def require_spoken_portuguese(transcript: dict) -> None:
    """Whisper language is the source speech, not translated subtitle language."""
    lang = str(transcript.get("language", "")).lower().split("-", 1)[0]
    if lang != "pt":
        raise ValueError("Revisão necessária: a fala original não foi identificada como português (pt).")
    segments = transcript.get("segments") or []
    text = " ".join(str(s.get("text", "")) for s in segments)
    if len(re.findall(r"\b[\wÀ-ÿ]+\b", text)) < 35:
        raise ValueError("Revisão necessária: transcrição portuguesa curta ou insuficiente.")


def select_contextual_portuguese_clips(transcript: dict, duration: float,
                                      count: int = 2) -> list[dict]:
    """Choose genuine timed Portuguese speech with an early hook and a full ending.

    When no strong selection exists, return [] for manual editorial review.
    """
    require_spoken_portuguese(transcript)
    segments = sorted(
        (s for s in transcript["segments"]
         if float(s.get("end", 0)) > float(s.get("start", 0)) and str(s.get("text", "")).strip()),
        key=lambda s: s["start"])
    if duration < 24 or not segments:
        return []
    desired = max(1, min(3, count))
    min_sec = min(28, max(18, int(duration * .46)))
    max_sec = min(85, max(min_sec, int(duration)))
    proposed = suggest(segments, duration, count=20, min_seconds=min_sec, max_seconds=max_sec)
    eligible = []
    for option in proposed:
        a, b = float(option["start"]), float(option["end"])
        included = [s for s in segments if float(s["end"]) > a and float(s["start"]) < b]
        if len(included) < 3:
            continue
        spoken = " ".join(str(s["text"]).strip() for s in included)
        words = re.findall(r"\b[\wÀ-ÿ]+\b", spoken)
        if len(words) < 35 or len(words) / max(1, b-a) < .72:
            continue
        opening = " ".join(str(s["text"]) for s in included
                           if float(s["start"]) < a + 9).lower()
        opening = re.sub(r"\s+", " ", opening)
        has_hook = any(phrase in opening for phrase in OPENERS) or "?" in opening
        if not has_hook:
            continue
        ending = str(included[-1]["text"]).strip()
        last_word = re.findall(r"[\wÀ-ÿ]+", ending.lower())
        if (not re.search(r"[.!?…][\"'”’]?\s*$", ending)
                or (last_word and last_word[-1] in BAD_ENDINGS)):
            continue
        eligible.append({**option, "start": a, "end": b,
                         "hook": " ".join(opening.split()[:16]),
                         "quality": "pt_speech_hook_and_complete_ending",
                         "score": option["score"] + 4})
    eligible.sort(key=lambda p: p["score"], reverse=True)
    selected = []
    for item in eligible:
        if any(max(0, min(item["end"], x["end"]) - max(item["start"], x["start"])) >
               .15 * min(item["end"]-item["start"], x["end"]-x["start"])
               for x in selected):
            continue
        selected.append(item)
        if len(selected) == desired:
            break
    return selected
