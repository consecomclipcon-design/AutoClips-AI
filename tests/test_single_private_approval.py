from autoclips import dashboard

def test_muzy_upload_requires_explicit_environment_approval(working, monkeypatch):
    monkeypatch.delenv("AUTOCLIPS_MUZY_PRIVATE_APPROVED_CLIP", raising=False)
    dashboard._queue_approved_muzy_private_upload()
    monkeypatch.setenv("AUTOCLIPS_MUZY_PRIVATE_APPROVED_CLIP", "clip_other")
    dashboard._queue_approved_muzy_private_upload()
