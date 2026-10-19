"""One-owner Google OAuth Web authorization for the AutoClips Railway worker.

Public connect is available only while no YouTube channel is linked, and
only the expected YouTube channel ID is allowed. Callback states are single-use
and expire after 10 minutes. All OAuth credentials are encrypted at rest.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from .settings import home

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = [UPLOAD_SCOPE, READONLY_SCOPE]
OAUTH_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN = "https://oauth2.googleapis.com/token"
CHANNEL_API = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"


def _config():
    names = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
             "YOUTUBE_EXPECTED_CHANNEL_ID", "MCP_GATEWAY_TOKEN")
    v = {n: os.getenv(n, "") for n in names}
    if any(not v[k] for k in names):
        raise RuntimeError("Google OAuth não configurado no Railway")
    if len(v["MCP_GATEWAY_TOKEN"]) < 32:
        raise RuntimeError("Chave de proteção do servidor inválida")
    if not v["GOOGLE_REDIRECT_URI"].startswith("https://"):
        raise RuntimeError("O callback OAuth exige HTTPS em produção")
    if not v["YOUTUBE_EXPECTED_CHANNEL_ID"].startswith("UC") or len(v["YOUTUBE_EXPECTED_CHANNEL_ID"]) != 24:
        raise RuntimeError("Configure o ID de canal esperado")
    return v


def _cipher():
    secret = _config()["MCP_GATEWAY_TOKEN"].encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def vault_path() -> Path:
    return home() / "youtube-oauth.enc"


def has_connection() -> bool:
    return vault_path().is_file()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(home() / "autoclips.sqlite3", timeout=20)
    conn.execute("""CREATE TABLE IF NOT EXISTS youtube_oauth_states
                    (digest TEXT PRIMARY KEY, expires TEXT NOT NULL)""")
    return conn


def safe_diagnostics() -> dict:
    """Minimal non-secret diagnostics for operators and deploy logs."""
    required = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI",
                "YOUTUBE_EXPECTED_CHANNEL_ID", "MCP_GATEWAY_TOKEN")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        return {"ready": False, "connected": False, "reason": "missing_environment",
                "missing_variable_names": missing}
    try:
        _config()
    except RuntimeError:
        return {"ready": False, "connected": False, "reason": "invalid_environment"}
    if has_connection():
        try:
            data = read_connection()
            return {"ready": True, "connected": True, "reason": "connected",
                    "channel_id": data["channel_id"]}
        except Exception:
            return {"ready": False, "connected": False, "reason": "stored_token_unreadable"}
    try:
        conn = _db()
        try:
            conn.execute("SELECT 1 FROM youtube_oauth_states LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception as exc:
        return {"ready": False, "connected": False, "reason": "storage_or_database_error",
                "error_type": type(exc).__name__}
    return {"ready": True, "connected": False, "reason": "authorization_required"}


def start_authorization() -> str:
    conf = _config()
    if has_connection():
        raise RuntimeError("Canal já conectado; reconexão requer autorização administrativa")
    state = secrets.token_urlsafe(32)
    digest = hashlib.sha256(state.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    with _db() as conn:
        conn.execute("DELETE FROM youtube_oauth_states WHERE expires < ?", (datetime.now(timezone.utc).isoformat(),))
        conn.execute("INSERT INTO youtube_oauth_states (digest,expires) VALUES (?,?)", (digest, expires))
    q = urlencode({
        "client_id": conf["GOOGLE_CLIENT_ID"], "redirect_uri": conf["GOOGLE_REDIRECT_URI"],
        "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
        "prompt": "consent", "state": state,
    })
    return OAUTH_AUTH + "?" + q


def _consume_state(state: str) -> None:
    if not isinstance(state, str) or len(state) > 160 or len(state) < 24:
        raise ValueError("Estado OAuth inválido")
    digest = hashlib.sha256(state.encode()).hexdigest()
    with _db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT expires FROM youtube_oauth_states WHERE digest=?", (digest,)).fetchone()
        conn.execute("DELETE FROM youtube_oauth_states WHERE digest=?", (digest,))
        if not row or datetime.fromisoformat(row[0]) <= datetime.now(timezone.utc):
            raise ValueError("Estado OAuth expirado ou já usado")


def _request_json(request: Request) -> dict:
    with urlopen(request, timeout=30) as response:
        if response.status not in (200, 201):
            raise RuntimeError("Falha de autorização Google")
        return json.loads(response.read(128_000))


def _verify_channel(access_token: str) -> dict:
    response = _request_json(Request(CHANNEL_API, headers={"Authorization": "Bearer " + access_token}))
    channels = response.get("items", [])
    if len(channels) != 1 or channels[0].get("id") != _config()["YOUTUBE_EXPECTED_CHANNEL_ID"]:
        raise PermissionError("Esta conta não controla o canal YouTube esperado para o ClipCon")
    return {"id": channels[0]["id"], "name": channels[0].get("snippet", {}).get("title", "")}


def _write_vault(credentials_info: dict, channel_id: str, channel_name: str) -> None:
    payload = {"credentials": credentials_info, "channel_id": channel_id, "channel_name": channel_name}
    encrypted = _cipher().encrypt(json.dumps(payload).encode())
    path = vault_path()
    tmp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name == "posix":
            path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


def complete_authorization(code: str, state: str) -> dict:
    conf = _config()
    _consume_state(state)
    if has_connection():
        raise RuntimeError("Canal já conectado; autorização duplicada recusada")
    if not isinstance(code, str) or not code or len(code) > 4096:
        raise ValueError("Código OAuth inválido")
    payload = urlencode({
        "code": code, "client_id": conf["GOOGLE_CLIENT_ID"],
        "client_secret": conf["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": conf["GOOGLE_REDIRECT_URI"],
        "grant_type": "authorization_code",
    }).encode()
    token = _request_json(Request(OAUTH_TOKEN, data=payload,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"}))
    actual_scopes = set(str(token.get("scope", "")).split())
    if not set(SCOPES).issubset(actual_scopes):
        raise PermissionError("OAuth não concedeu as permissões YouTube necessárias")
    if not token.get("refresh_token") or not token.get("access_token"):
        raise PermissionError("Google não retornou autorização offline; refaça o consentimento")
    channel = _verify_channel(token["access_token"])
    expiry = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(token.get("expires_in", 3600))))
    info = {
        "token": token["access_token"], "refresh_token": token["refresh_token"],
        "token_uri": OAUTH_TOKEN, "client_id": conf["GOOGLE_CLIENT_ID"],
        "client_secret": conf["GOOGLE_CLIENT_SECRET"], "scopes": SCOPES,
        "expiry": expiry.isoformat().replace("+00:00", "Z"),
    }
    _write_vault(info, channel["id"], channel["name"])
    return {"status": "connected", "channel": channel}


def read_connection() -> dict:
    try:
        blob = vault_path().read_bytes()
        data = json.loads(_cipher().decrypt(blob))
        conf = _config()
        if data.get("channel_id") != conf["YOUTUBE_EXPECTED_CHANNEL_ID"]:
            raise RuntimeError("O canal armazenado não corresponde ao canal autorizado")
        # Rotate Google Client Secret via Railway without invalidating the
        # encrypted refresh token or requiring another Google consent screen.
        data["credentials"]["client_secret"] = conf["GOOGLE_CLIENT_SECRET"]
        return data
    except FileNotFoundError:
        raise RuntimeError("YouTube não conectado; abra a página de autorização") from None
    except (InvalidToken, ValueError, KeyError, json.JSONDecodeError):
        raise RuntimeError("Credenciais salvas não podem ser descriptografadas; verifique a chave do gateway") from None


def save_refreshed_credentials(creds) -> None:
    saved = read_connection()
    _write_vault(json.loads(creds.to_json()), saved["channel_id"], saved.get("channel_name", ""))


def connection_status() -> dict:
    if not has_connection():
        return {"connected": False, "expectedChannelId": os.getenv("YOUTUBE_EXPECTED_CHANNEL_ID")}
    data = read_connection()
    return {"connected": True, "channelId": data["channel_id"], "channelName": data.get("channel_name", "")}
