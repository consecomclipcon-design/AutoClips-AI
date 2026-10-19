"""External image choice must match the subject, remain HTTPS and public domain."""
from autoclips.contextual_image import topic_terms, choose_public_domain_image


def test_topic_terms_strip_generic_words():
    assert topic_terms("Ramon Dino conta a história do Mr Olympia")[:2]==["ramon","dino"]


def test_reject_unrelated_licensed_photo():
    payload={"query":{"pages":{"1":{"title":"File:Mountain blue sky.jpg","imageinfo":[{
        "thumburl":"https://upload.wikimedia.org/wikipedia/commons/test.jpg",
        "extmetadata":{"LicenseShortName":{"value":"CC0"}}}]}}}}
    assert choose_public_domain_image(payload,"Ramon Dino e Olympia") is None


def test_reject_restricted_image_even_when_related():
    payload={"query":{"pages":{"1":{"title":"File:Ramon Dino.jpg","imageinfo":[{
        "thumburl":"https://upload.wikimedia.org/wikipedia/commons/test.jpg",
        "extmetadata":{"LicenseShortName":{"value":"CC BY-SA 4.0"}}}]}}}}
    assert choose_public_domain_image(payload,"Ramon Dino entrevista") is None


def test_select_relevant_cc0_from_trusted_host():
    payload={"query":{"pages":{"1":{"title":"File:Ramon Dino competition.jpg","imageinfo":[{
        "thumburl":"https://upload.wikimedia.org/wikipedia/commons/thumb/test.jpg",
        "extmetadata":{"LicenseShortName":{"value":"CC0"}}}]}}}}
    assert choose_public_domain_image(payload,"Ramon Dino entrevista")["license"]=="cc0"

def test_curated_olympia_photo_licensed_and_exact_real_source():
    from autoclips.contextual_image import curated_context_image
    result=curated_context_image("Depois do Olympia 2026: o que vem pela frente?")
    assert result["license"]=="cc by 4.0"
    assert "Foto ilustrativa de 2025" in result["credit"]
    assert result["url"]=="https://upload.wikimedia.org/wikipedia/commons/5/5d/Ramon_Dino_shows_his_Mr._Olympia_trophy_(2025).jpg"
    assert "creativecommons.org/licenses/by/4.0/" in result["license_url"]


def test_curated_supplement_photo_is_public_domain():
    from autoclips.contextual_image import curated_context_image
    result=curated_context_image("Qual suplemento tomar? Muzy responde")
    assert result["license"]=="public domain"
    assert result["url"]=="https://upload.wikimedia.org/wikipedia/commons/7/7b/Bodybuilding_supplement_high_protein_drink_mix_700g.jpg"


def test_curated_lookup_never_guesses_arbitrary_context():
    from autoclips.contextual_image import curated_context_image
    assert curated_context_image("Uma história surpreendente sem assunto") is None
