from __future__ import annotations
import math
import re

HOOKS = (
    "ninguém", "você sabia", "não acredito", "segredo", "o problema", "a verdade",
    "aprendi", "nunca", "incrível", "absurdo", "errei", "imagina", "porque",
    "por quê", "eu descobri", "o que aconteceu", "surpresa", "o melhor",
    "o pior", "o erro", "por isso", "sabe o que", "história", "conselho",
    "the secret", "what happened", "you won't believe", "never", "mistake", "why",
)


def suggest(segments: list[dict], duration: float, count: int = 5,
            min_seconds: int = 25, max_seconds: int = 60) -> list[dict]:
    """Pré-seleção HEURÍSTICA, não predição estatística de viralização.

    O cliente IA deve ler a transcrição e refinar manualmente os tempos.
    """
    if not 1 <= count <= 20 or not 10 <= min_seconds <= max_seconds <= 180:
        raise ValueError("Parâmetros inválidos: 1–20 sugestões, durações de 10–180s")
    if not segments:
        return []
    segments = sorted(segments, key=lambda s: s["start"])
    candidates: list[dict] = []
    for i, s in enumerate(segments):
        start = max(0.0, float(s["start"]) - 0.3)
        if start + min_seconds > duration:
            continue
        min_end, max_end = start + min_seconds, min(start + max_seconds, duration)
        ends = [j for j in range(i, len(segments)) if min_end <= segments[j]["end"] <= max_end]
        if not ends:
            # Para legendas com grandes blocos, permita encerramento por tempo.
            end = max_end
        else:
            # Final próximo de pontuação e 45s (se possível).
            best_j = max(ends, key=lambda j: (
                1.0 if re.search(r"[.!?…]$", segments[j]["text"].strip()) else 0.0
            ) - abs(segments[j]["end"] - (start + 45)) / 100)
            end = float(segments[best_j]["end"])
        selected = [x for x in segments if x["end"] > start and x["start"] < end]
        text = " ".join(x["text"].strip() for x in selected)
        normalized = text.lower()
        hits = sum(1 for h in HOOKS if h in normalized)
        words = re.findall(r"\w+", text)
        speaking = len(words) / max(1, end - start)
        opening = " ".join(x["text"] for x in selected[:2]).lower()
        hook_early = sum(1 for h in HOOKS if h in opening)
        penalty = max(0, 1.0 - speaking) * 0.5
        score = round(hits * 2 + hook_early * 2 + min(speaking, 3) - penalty, 2)
        candidates.append({"start": round(start, 2), "end": round(end, 2),
                           "score": score, "text": text[:1600],
                           "reason": "Avaliação heurística de ganchos, ritmo e continuidade (revisar com IA)"})
    candidates.sort(key=lambda r: r["score"], reverse=True)
    selected: list[dict] = []
    for candidate in candidates:
        # Evita cortes quase idênticos; permite até 20% de interseção.
        if any((min(candidate["end"], other["end"]) - max(candidate["start"], other["start"])) >
               .2 * min(candidate["end"]-candidate["start"], other["end"]-other["start"])
               for other in selected):
            continue
        selected.append(candidate)
        if len(selected) >= count:
            break
    return selected
