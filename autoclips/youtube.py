from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from .settings import setting_path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def secrets_file() -> Path:
    return setting_path("GOOGLE_CLIENT_SECRETS", "./client_secret.json")


def token_file() -> Path:
    return setting_path("GOOGLE_TOKEN_FILE", "./token.json")


def _save_creds(creds) -> None:
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)


def authorize_locally() -> str:
    """Autorização interativa executada SOMENTE pelo operador do computador."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not secrets_file().is_file():
        raise FileNotFoundError("Configure GOOGLE_CLIENT_SECRETS e baixe as credenciais OAuth do Google Cloud")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file()), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    _save_creds(credentials)
    return "Autorização concluída. Credenciais gravadas localmente; nunca compartilhe token.json."


def client():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    if not token_file().is_file():
        raise RuntimeError("Canal não conectado. Execute python -m autoclips.youtube_auth neste computador.")
    creds = Credentials.from_authorized_user_file(str(token_file()), scopes=SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_creds(creds)
        else:
            raise RuntimeError("Token inválido ou sem permissão; execute python -m autoclips.youtube_auth")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel() -> dict:
    result = client().channels().list(part="id,snippet", mine=True).execute()
    channels = result.get("items", [])
    if len(channels) != 1:
        raise RuntimeError("Conta sem canal identificável. Reconecte escolhendo o canal correto.")
    c = channels[0]
    return {"id": c["id"], "name": c.get("snippet", {}).get("title", "Canal sem nome")}


def validate_schedule(publish_at: str | None, privacy: str) -> str | None:
    if not publish_at:
        return None
    if privacy != "private":
        raise ValueError("Para agendar, escolha privacidade 'private' e informe publish_at")
    d = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    if not d.tzinfo or d.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise ValueError("publish_at precisa ser ISO 8601 com fuso e horário futuro")
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def upload(file_path: str, title: str, description: str, privacy: str,
           made_for_kids: bool, channel_id: str, publish_at: str | None = None) -> str:
    from googleapiclient.http import MediaFileUpload
    current = channel()
    if current["id"] != channel_id:
        raise RuntimeError("Canal conectado mudou. Upload cancelado por segurança.")
    if not Path(file_path).is_file():
        raise FileNotFoundError("Vídeo renderizado não encontrado")
    status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids}
    if publish_at:
        status["publishAt"] = validate_schedule(publish_at, privacy)
    body = {"snippet": {"title": title, "description": description, "categoryId": "22"},
            "status": status}
    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    request = client().videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _progress, response = request.next_chunk()
    if not response or "id" not in response:
        raise RuntimeError("API não retornou ID de vídeo; confira o canal antes de tentar novamente")
    return "https://www.youtube.com/watch?v=" + response["id"]
