from __future__ import annotations
import os
from pathlib import Path


def load_dotenv() -> None:
    """Carrega variáveis não definidas de .env sem dependência externa."""
    env = Path.cwd() / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().isidentifier():
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv()


def home() -> Path:
    value = os.getenv("AUTOCLIPS_HOME", "./storage")
    p = Path(value).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    for sub in ("imports", "projects", "exports"):
        (p / sub).mkdir(exist_ok=True)
    return p


def setting_path(name: str, fallback: str) -> Path:
    return Path(os.getenv(name, fallback)).expanduser().resolve()


def youtube_import_allowed() -> bool:
    return os.getenv("ALLOW_YOUTUBE_IMPORT", "false").strip().lower() == "true"
