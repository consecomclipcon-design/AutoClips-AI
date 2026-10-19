"""Context-preserving cut selection. The model chooses the semantic anchor;
this helper expands the boundaries to preserve lead-in and payoff.
"""
from __future__ import annotations
import math


def contextual_window(segments: list[dict], anchor_start: float, anchor_end: float,
                      min_seconds: float = 35, max_seconds: float = 90) -> dict:
    if not 15 <= min_seconds <= max_seconds <= 180:
        raise ValueError('Use durations between 15 and 180 seconds')
    if not all(map(math.isfinite, [anchor_start, anchor_end])) or anchor_start < 0 or anchor_end <= anchor_start:
        raise ValueError('Invalid anchor window')
    if anchor_end-anchor_start > max_seconds:
        raise ValueError('Anchor already exceeds maximum duration')
    timeline = sorted((dict(s) for s in segments if float(s['end']) > float(s['start'])), key=lambda s: s['start'])
    if not timeline:
        raise ValueError('Timestamped transcript is required')
    centers = [i for i, s in enumerate(timeline) if s['end'] > anchor_start and s['start'] < anchor_end]
    if not centers:
        raise ValueError('Anchor does not coincide with transcript')
    first,last=centers[0],centers[-1]
    # Preserve one preceding thought whenever it fits; an anchor by itself
    # often lacks the question or setup needed for the listener.
    lead=max(0, first-1)
    start=float(timeline[lead]['start'])
    if anchor_end-start > max_seconds:
        start=float(timeline[first]['start'])
    end=max(anchor_end,float(timeline[last]['end']))
    idx=last+1
    while end-start < min_seconds and idx < len(timeline):
        next_end=float(timeline[idx]['end'])
        if next_end-start > max_seconds:
            break
        end=next_end
        idx+=1
    if end-start < min_seconds:
        # Extend into the next scene only within the source duration.
        end=min(float(timeline[-1]['end']), start+min_seconds, start+max_seconds)
    if end-start < min_seconds-1e-3:
        raise ValueError('Unable to obtain a contextual clip of the requested duration')
    return {'start': round(start,2), 'end': round(end,2), 'duration':round(end-start,2),
            'rationale':'Inclui fala preparatória e mantém a conclusão do trecho; revisar vídeo e áudio antes de publicar'}
