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
