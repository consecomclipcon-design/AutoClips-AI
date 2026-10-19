"""Do not auto-publish non-Portuguese or contextless clips."""
import pytest
from autoclips.editorial import require_spoken_portuguese, select_contextual_portuguese_clips


def sample(lang="pt", complete=True, hook=True):
    sentences = [
      "Você sabia que o atleta treinava todos os dias antes da competição?",
      "Ele começou sem equipamento e aprendeu a trabalhar com o próprio corpo.",
      "A diferença apareceu quando ele encontrou uma rotina mais inteligente.",
      "Durante meses, ele manteve uma disciplina que ninguém imaginava possível.",
      "No fim, ele melhorou a técnica e conseguiu completar o desafio."
    ]
    if not hook: sentences[0] = "Ele estava fazendo exercícios durante a tarde."
    if not complete: sentences[-1] = "Mas aí ele encontrou a razão porque"
    return {"language":lang,"segments":[
        {"start":i*9.0,"end":(i+1)*9.0,"text":s} for i,s in enumerate(sentences)]}


def test_english_audio_never_enters_portuguese_auto_queue():
    with pytest.raises(ValueError,match="português"):
        select_contextual_portuguese_clips(sample("en"),45)


def test_absent_language_cannot_masquerade_as_pt():
    with pytest.raises(ValueError,match="português"):
        require_spoken_portuguese(sample("und"))


def test_pt_with_hook_and_ending_produces_timed_editorial_suggestion():
    items=select_contextual_portuguese_clips(sample(),45,count=2)
    assert items and items[0]["hook"]
    assert items[0]["quality"]=="pt_speech_hook_and_complete_ending"
    assert items[0]["end"] <= 45


def test_incomplete_ending_is_not_auto_approved():
    assert select_contextual_portuguese_clips(sample(complete=False),45) == []


def test_generic_opening_cannot_be_marked_viral():
    assert select_contextual_portuguese_clips(sample(hook=False),45) == []
