"""Short, content-grounded, readable Portuguese hooks for static split-screen captions.

The hook is a two-line editorial question/promise derived from the source
title and actual spoken window, not a generative claim of virality. In doubt,
use the actual words instead of inventing a revelation.
"""
from __future__ import annotations

import re
import unicodedata

MAX_LINE = 26
STOPWORDS = {
    "sobre", "voce", "voces", "para", "tambem", "isso", "esse", "essa",
    "dessa", "desse", "qual", "quais", "como", "porque", "quando", "aqui",
    "ainda", "agora", "depois", "antes", "muito", "mais", "nossa", "hoje",
    "estou", "esta", "este", "tem", "com", "que", "ele", "ela", "uma",
    "algum", "algo", "minha", "meu", "seu", "sua", "entre", "seria"
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[{}\\\r\n\t]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -,:;")
    return text


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", _fold(text))
            if w not in STOPWORDS}


def _fit_two_lines(text: str) -> tuple[str, str] | None:
    """Split a complete short phrase at a word boundary; no truncated claims."""
    text = _clean(text).upper()
    if len(text) < 12 or len(text) > 2 * MAX_LINE + 1:
        return None
    words = text.split()
    splits = [
        (" ".join(words[:i]), " ".join(words[i:]))
        for i in range(1, len(words))
    ]
    possible = [(a, b) for a,b in splits
                if 6 <= len(a) <= MAX_LINE and 5 <= len(b) <= MAX_LINE]
    if not possible:
        return None
    return min(possible, key=lambda pair: abs(len(pair[0]) - len(pair[1])))


def _source_window(segments: list[dict], start: float, end: float) -> str:
    return " ".join(
        str(seg.get("text", "")).strip()
        for seg in segments
        if float(seg.get("end", 0)) > start and float(seg.get("start", 0)) < end
    )


def generate_static_hook(title: str, segments: list[dict],
                         start: float, end: float) -> dict:
    """Find an emotionally engaging but factually grounded, persistent hook.

    Source title templates are used only when relevant subject words are
    present in speech. Otherwise the speech itself is the evidence.
    """
    spoken = _clean(_source_window(segments, start, end))
    if not spoken or len(spoken.split()) < 8:
        raise ValueError("Trecho sem fala suficiente para criar gancho fiel.")
    title_clean = _clean(title)
    normalized_title = _fold(title_clean)
    normalized_spoken = _fold(spoken)
    shared = _keywords(title_clean) & _keywords(spoken)
    templates = (
        (("suplement",), ("suplement", "creatina", "whey", "vitamina"),
         "QUAL SUPLEMENTO", "VOCÊ DEVE TOMAR?"),
        (("olympia",), ("olympia", "competicao", "titulo", "fisicultur"),
         "O QUE VEM", "DEPOIS DO OLYMPIA?"),
        (("doping",), ("doping", "anabolizante", "hormon"),
         "O QUE ELE CONTOU", "SOBRE DOPING?"),
        (("academia",), ("academia", "treino", "musculacao"),
         "O QUE TEM", "NESSA ACADEMIA?"),
        (("vaquinha",), ("vaquinha", "dinheiro", "ajuda"),
         "O QUE MUDOU", "COM ESSA VAQUINHA?"),
        (("treino",), ("treino", "peito", "exercicio"),
         "O QUE MUDA", "NESSE TREINO?"),
    )
    for title_terms, speech_terms, upper, emphasis in templates:
        if (any(t in normalized_title for t in title_terms)
                and any(t in normalized_spoken for t in speech_terms)):
            return {"top":upper, "bottom":emphasis,
                    "source":"subject_supported_by_speech",
                    "evidence":next(t for t in speech_terms if t in normalized_spoken)}
    # Prefer an authentic question from this cut over clickbait guesses.
    for sentence in re.findall(r"[^.!?]{8,100}\?", spoken):
        candidate = _clean(sentence)
        formatted = _fit_two_lines(candidate)
        if formatted:
            return {"top":formatted[0], "bottom":formatted[1],
                    "source":"spoken_question", "evidence":candidate[:100]}
    # A title question is usable if the cut demonstrably talks about its topic.
    if shared and "?" in title_clean:
        formatted = _fit_two_lines(title_clean)
        if formatted:
            return {"top":formatted[0], "bottom":formatted[1],
                    "source":"title_supported_by_speech",
                    "evidence":", ".join(sorted(shared)[:3])}
    # Last resort: keep the exact audible excerpt and leave an honest ellipsis.
    for sentence in re.split(r"[.!?…]", spoken):
        candidate = _clean(sentence)
        if len(candidate) < 15:
            continue
        words = candidate.split()
        for n in range(min(len(words), 11), 4, -1):
            prefix = " ".join(words[:n]).rstrip(" ,:;") + "…"
            formatted = _fit_two_lines(prefix)
            if formatted:
                return {"top":formatted[0], "bottom":formatted[1],
                        "source":"literal_spoken_teaser",
                        "evidence":candidate[:100]}
    raise ValueError("Nenhum gancho curto e fiel pôde ser gerado para o trecho.")
