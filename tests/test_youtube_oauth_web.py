"""Safe offline end-to-end tests for the server-side OAuth web flow."""
import asyncio
import json
import os
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import pytest

from autoclips import oauth_web
from autoclips.cloud_auth import BearerGate


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIPS_HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "testing-only-placeholder")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.test/oauth/youtube/callback")
    monkeypatch.setenv("YOUTUBE_EXPECTED_CHANNEL_ID", "UC" + "x" * 22)
    monkeypatch.setenv("MCP_GATEWAY_TOKEN", "stable-and-long-private-gateway-token-for-test")
    return tmp_path


def extract_state(url):
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "accounts.google.com"
    values = parse_qs(parsed.query)
    assert values["access_type"] == ["offline"]
    assert values["prompt"] == ["consent"]
    assert "youtube.upload" in values["scope"][0]
    assert "youtube.readonly" in values["scope"][0]
    assert values["redirect_uri"] == ["https://example.test/oauth/youtube/callback"]
    return values["state"][0]


def simulate_google(monkeypatch, channel_id, scopes=None):
    async_calls = []
    def fake(request):
        url = request.full_url
        async_calls.append(url.split("?")[0])
        if url.startswith(oauth_web.OAUTH_TOKEN):
            return {"access_token": "not-a-real-token", "refresh_token": "not-a-real-refresh",
                    "scope": scopes or " ".join(oauth_web.SCOPES), "expires_in": 3600}
        if url.startswith("https://www.googleapis.com/youtube/v3/channels?"):
            return {"items": [{"id": channel_id, "snippet": {"title": "ClipCon Test"}}]}
        raise AssertionError("unexpected Google endpoint")
    monkeypatch.setattr(oauth_web, "_request_json", fake)
    return async_calls


def test_preflight_explains_authorization_pending_without_secrets(setup, monkeypatch):
    status = oauth_web.safe_diagnostics()
    assert status["ready"] is True
    assert status["connected"] is False
    assert status["reason"] == "authorization_required"
    assert "testing-only-placeholder" not in str(status)


def test_preflight_distinguishes_missing_env_and_connection(setup, monkeypatch):
    monkeypatch.delenv("GOOGLE_REDIRECT_URI")
    assert oauth_web.safe_diagnostics()["reason"] == "missing_environment"
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.test/oauth/youtube/callback")
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "x" * 22)
    oauth_web.complete_authorization("good-code", state)
    status = oauth_web.safe_diagnostics()
    assert status["reason"] == "connected"
    assert status["connected"] is True


def test_oauth_url_and_encrypted_storage(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    calls = simulate_google(monkeypatch, "UC" + "x" * 22)
    result = oauth_web.complete_authorization("test-auth-code", state)
    assert result["channel"]["name"] == "ClipCon Test"
    assert len(calls) == 2
    saved = oauth_web.vault_path().read_bytes()
    assert b"not-a-real-refresh" not in saved and b"testing-only-placeholder" not in saved
    assert os.stat(oauth_web.vault_path()).st_mode & 0o777 == 0o600
    assert oauth_web.connection_status()["connected"] is True
    with pytest.raises(ValueError):
        oauth_web.complete_authorization("again", state)
    with pytest.raises(RuntimeError):
        oauth_web.start_authorization()


def test_wrong_channel_rejected_without_persisting(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "y" * 22)
    with pytest.raises(PermissionError):
        oauth_web.complete_authorization("test-auth-code", state)
    assert not oauth_web.vault_path().exists()


def test_missing_upload_scope_rejected(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "x" * 22, scopes="openid email")
    with pytest.raises(PermissionError):
        oauth_web.complete_authorization("test-auth-code", state)
    assert not oauth_web.vault_path().exists()


def test_google_client_secret_rotation_does_not_lose_refresh_token(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "x" * 22)
    oauth_web.complete_authorization("code", state)
    first = oauth_web.read_connection()
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "rotated-google-client-secret-from-railway")
    second = oauth_web.read_connection()
    assert first["credentials"]["refresh_token"] == second["credentials"]["refresh_token"]
    assert second["credentials"]["client_secret"] == "rotated-google-client-secret-from-railway"


def test_state_replay_is_rejected_without_google_call(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "y" * 22)
    with pytest.raises(PermissionError):
        oauth_web.complete_authorization("wrong-account", state)
    with pytest.raises(ValueError):
        oauth_web.complete_authorization("other", state)


def test_gateway_key_mismatch_fail_closed(setup, monkeypatch):
    state = extract_state(oauth_web.start_authorization())
    simulate_google(monkeypatch, "UC" + "x" * 22)
    oauth_web.complete_authorization("code", state)
    monkeypatch.setenv("MCP_GATEWAY_TOKEN", "completely-different-encryption-master-key-001")
    with pytest.raises(RuntimeError):
        oauth_web.read_connection()


def test_oauth_callbacks_public_but_others_require_bearer(setup):
    seen = []
    async def inner(scope, receive, send):
        seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    auth = BearerGate(inner, os.environ["MCP_GATEWAY_TOKEN"])
    async def call(path, method="GET", bearer=False):
        sent = []
        headers = [(b"authorization", ("Bearer " + os.environ["MCP_GATEWAY_TOKEN"]).encode())] if bearer else []
        async def send(chunk):
            sent.append(chunk)
        await auth({"type": "http", "path": path, "method": method, "headers": headers},
                   lambda: None, send)
        return sent[0]["status"]
    assert asyncio.run(call("/oauth/youtube/callback")) == 200
    assert asyncio.run(call("/oauth/youtube/start")) == 200
    assert asyncio.run(call("/oauth/youtube/start", method="POST")) == 401
    assert asyncio.run(call("/api/youtube/status")) == 401
    assert asyncio.run(call("/api/youtube/status", bearer=True)) == 200
    assert seen == ["/oauth/youtube/callback", "/oauth/youtube/start", "/api/youtube/status"]
