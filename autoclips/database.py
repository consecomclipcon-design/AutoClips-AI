from __future__ import annotations
import json
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any
from .settings import home


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(home() / "autoclips.sqlite3", timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, source TEXT NOT NULL,
          name TEXT NOT NULL, media TEXT, transcript TEXT, duration REAL,
          status TEXT NOT NULL, error TEXT, created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clips (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, start REAL NOT NULL,
          end REAL NOT NULL, style TEXT NOT NULL, path TEXT,
          status TEXT NOT NULL, error TEXT, created TEXT NOT NULL,
          uploaded_url TEXT,
          FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_id TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT, error TEXT,
          created TEXT NOT NULL, updated TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          token TEXT PRIMARY KEY, clip_id TEXT NOT NULL,
          title TEXT NOT NULL, description TEXT NOT NULL,
          privacy TEXT NOT NULL, made_for_kids INTEGER NOT NULL,
          publish_at TEXT, channel_id TEXT NOT NULL,
          expires TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
        );
        """)
        # Executores em memória não persistem após reinício; nunca indicar que continuam.
        c.execute("UPDATE jobs SET status='interrupted', error='Servidor reiniciado durante a execução', updated=? WHERE status IN ('queued','running')", (now(),))


def newid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def one(table: str, id: str) -> dict[str, Any]:
    if table not in {"projects", "clips", "jobs"}:
        raise ValueError("Tabela inválida")
    with conn() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
    if not row:
        raise ValueError(f"{table}: registro não encontrado")
    return dict(row)


def rows(table: str, column: str | None = None, value: str | None = None, max_results: int = 30) -> list[dict]:
    if table not in {"projects", "clips", "jobs"} or (column not in {None, "project_id", "target_id"}):
        raise ValueError("Consulta inválida")
    with conn() as c:
        q = f"SELECT * FROM {table}"
        args: list = []
        if column:
            q += f" WHERE {column}=?"
            args.append(value)
        q += " ORDER BY created DESC LIMIT ?"
        args.append(min(max_results, 100))
        return [dict(r) for r in c.execute(q, args).fetchall()]


def update(table: str, id: str, **values: Any) -> None:
    if table not in {"projects", "clips", "jobs"} or not values:
        raise ValueError("Atualização inválida")
    allowed = {
        "projects": {"name", "media", "transcript", "duration", "status", "error"},
        "clips": {"path", "status", "error", "uploaded_url"},
        "jobs": {"status", "result", "error", "updated"},
    }
    if set(values) - allowed[table]:
        raise ValueError("Campos inválidos")
    clause = ",".join(f"{k}=?" for k in values)
    with conn() as c:
        c.execute(f"UPDATE {table} SET {clause} WHERE id=?", [*values.values(), id])


def reserve_approval(clip_id: str, title: str, description: str, privacy: str,
                     made_for_kids: bool, publish_at: str | None, channel_id: str) -> dict:
    token = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    with conn() as c:
        c.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,0)",
                  (token, clip_id, title, description, privacy, int(made_for_kids),
                   publish_at, channel_id, expires))
    return {"approval_token": token, "expires": expires}


def consume_approval(token: str) -> dict:
    # Transação evita uploads duplicados sob concorrência.
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT * FROM approvals WHERE token=?", (token,)).fetchone()
        if not r or r["consumed"] or datetime.fromisoformat(r["expires"]) < datetime.now(timezone.utc):
            raise ValueError("Aprovação inválida, já usada ou expirada")
        c.execute("UPDATE approvals SET consumed=1 WHERE token=? AND consumed=0", (token,))
    return dict(r)
