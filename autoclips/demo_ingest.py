"""Restricted one-time import of the owner's expressly approved 80-second demo clip.

GitHub Actions OIDC authorizes an exact workflow running on main; the binary
must match the SHA256 of the previously reviewed MP4. Never log OIDC JWTs.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

from starlette.responses import JSONResponse

from .settings import home
from . import database as db
from . import pipeline

DEMO_SHA = "d284801ffe3de719e885e0146b9bd2ff29311db51cacf4253c2166a3bae5e055"
DEMO_SIZE = 26325600
DEMO_WORKFLOW = "consecomclipcon-design/AutoClips-AI/.github/workflows/upload-approved-demo.yml@refs/heads/main"
DEMO_REPOSITORY = "consecomclipcon-design/AutoClips-AI"
DEMO_AUDIENCE = "autoclips-clipcon-approved-80s-import"
DEMO_NAME = "A APOSTA QUE QUASE CUSTOU O CASAMENTO! #Shorts"
DEMO_DESCRIPTION = ("Corte de 80 segundos sobre a historia de Renato e Tati Cariani. "
                    "Trecho comentado do Ironcast. #RenatoCariani #Cortes #Shorts")


def _verify_github_oidc(token: str) -> dict:
    import jwt
    if not token or len(token) > 10_000:
        raise PermissionError("GitHub OIDC token missing or invalid")
    jwks = jwt.PyJWKClient("https://token.actions.githubusercontent.com/.well-known/jwks",
                          cache_jwk_set=True, lifespan=900, timeout=15)
    key = jwks.get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"],
                        audience=DEMO_AUDIENCE,
                        issuer="https://token.actions.githubusercontent.com",
                        options={"require": ["iss", "aud", "iat", "exp", "sub"]},
                        leeway=30)
    if (claims.get("repository") != DEMO_REPOSITORY or
        claims.get("ref") != "refs/heads/main" or
        claims.get("workflow_ref") != DEMO_WORKFLOW or
        claims.get("event_name") != "push"):
        raise PermissionError("This workflow is not authorized to seed the demo clip")
    return claims


def _existing_demo() -> dict | None:
    with db.conn() as c:
        row = c.execute("SELECT id,uploaded_url,status FROM clips WHERE id=?", ("clip_cariani_demo80",)).fetchone()
        if row:
            return dict(row)
    return None


async def receive_demo(request):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse({"error": "oidc_required"}, status_code=401)
    try:
        _verify_github_oidc(authorization[7:])
    except Exception as exc:
        print("DEMO_INGEST_AUTH_REJECTED", type(exc).__name__, flush=True)
        return JSONResponse({"error": "unauthorized_workflow"}, status_code=403)

    pipeline.init()
    existing = _existing_demo()
    if request.method == "GET":
        from .publish_queue import get_publication
        return JSONResponse({"clip": existing, "publication":
                             get_publication("clip_cariani_demo80") if existing else None},
                            headers={"cache-control": "no-store"})
    if existing:
        return JSONResponse({"state": "already_imported", **existing})
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) != DEMO_SIZE:
                return JSONResponse({"error": "unexpected_size"}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "bad_size"}, status_code=400)

    target = home() / "imports" / "cariani_80s_exact_approved.mp4"
    tmp = target.with_suffix(".part")
    sha = hashlib.sha256()
    count = 0
    try:
        with tmp.open("wb") as fd:
            async for chunk in request.stream():
                count += len(chunk)
                if count > DEMO_SIZE:
                    return JSONResponse({"error": "unexpected_size"}, status_code=413)
                sha.update(chunk)
                fd.write(chunk)
        if count != DEMO_SIZE or sha.hexdigest() != DEMO_SHA:
            return JSONResponse({"error": "source_hash_mismatch"}, status_code=422)
        os.replace(tmp, target)

        # Insert a single, immutable record; idempotency persists across retries.
        from .media import probe
        info = probe(target)
        if not 79.5 < float(info["duration"]) < 80.5:
            raise ValueError("Unexpected duration of approved short")
        now = db.now()
        with db.conn() as c:
            c.execute("""INSERT OR IGNORE INTO projects
                         (id,source_kind,source,name,media,transcript,duration,status,error,created)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      ("prj_cariani_demo80", "file", target.name, "Cariani aprovado — 80s",
                       str(target), None, 80.0, "ready", None, now))
            c.execute("""INSERT OR IGNORE INTO clips
                         (id,project_id,start,end,style,path,status,error,created,uploaded_url)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      ("clip_cariani_demo80", "prj_cariani_demo80", 0,80,"split",
                       str(target), "ready", None, now, None))
        from .dashboard import enqueue_publication
        result = enqueue_publication("clip_cariani_demo80", title=DEMO_NAME,
                                     description=DEMO_DESCRIPTION, explicitly_approved=True)
        return JSONResponse({"imported": True, "sha256": DEMO_SHA, "publication": result},status_code=202)
    except Exception as exc:
        print("DEMO_INGEST_ERROR", type(exc).__name__,flush=True)
        return JSONResponse({"error": "import_failed", "error_type": type(exc).__name__},status_code=500)
    finally:
        tmp.unlink(missing_ok=True)
