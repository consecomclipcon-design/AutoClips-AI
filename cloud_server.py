"""HTTP transport for Railway and other trusted, one-owner deployments.

Every endpoint except /health requires MCP_GATEWAY_TOKEN (64+ recommended).
This gateway is not OAuth 2.1. Direct ChatGPT custom MCP installation needs
an OIDC/OAuth authorization provider; do not advertise this as ChatGPT-ready.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
import json

from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route

from autoclips.cloud_auth import BearerGate
from autoclips import oauth_web, dashboard, demo_ingest
from autoclips.upload_http import upload_media
from autoclips.api_http import create_project, status_job
from server import mcp


async def health(request):
    return JSONResponse({"status": "ok", "service": "autoclips-ai", "mode": "private-mcp"})


async def youtube_oauth_start(request):
    """One-owner, first-time-only Google consent; authenticated channel is pinned."""
    status = oauth_web.safe_diagnostics()
    if status["reason"] == "connected":
        return PlainTextResponse(
            "O canal ja esta conectado ao AutoClips. Nao e necessario autorizar novamente.",
            status_code=409, headers={"cache-control": "no-store"},
        )
    if not status["ready"]:
        return PlainTextResponse(
            "OAuth ainda indisponivel: " + status["reason"] +
            (". Variaveis: " + ", ".join(status.get("missing_variable_names", [])) if status.get("missing_variable_names") else ""),
            status_code=503, headers={"cache-control": "no-store"},
        )
    try:
        return RedirectResponse(oauth_web.start_authorization(), status_code=302,
                                headers={"cache-control": "no-store", "referrer-policy": "no-referrer"})
    except Exception as exc:
        print("AUTOCLIPS_OAUTH_START_ERROR", type(exc).__name__, flush=True)
        return PlainTextResponse(
            "Nao foi possivel iniciar o OAuth: erro de estado ou armazenamento.",
            status_code=503, headers={"cache-control": "no-store"},
        )


async def youtube_oauth_callback(request):
    """Google redirects here; single-use state, channel ID and scope checks are mandatory."""
    if request.query_params.get("error"):
        return PlainTextResponse("Permissão negada. Nada foi conectado.", status_code=403)
    try:
        result = oauth_web.complete_authorization(
            request.query_params.get("code", ""), request.query_params.get("state", ""),
        )
        return PlainTextResponse("YouTube conectado ao AutoClips: " + result["channel"]["name"],
                                 headers={"cache-control": "no-store", "referrer-policy": "no-referrer"})
    except Exception:
        return PlainTextResponse("Autorização falhou. Confirme o canal ClipCon e o callback no Google Cloud.",
                                 status_code=400, headers={"cache-control": "no-store"})


async def youtube_connection_status(request):
    try:
        return JSONResponse(oauth_web.connection_status(), headers={"cache-control": "no-store"})
    except Exception:
        return JSONResponse({"connected": False, "error": "authorization_unavailable"}, status_code=503)


@asynccontextmanager
async def lifespan(app):
    diagnostics = oauth_web.safe_diagnostics()
    # Safe, non-secret diagnostic (no OAuth codes, tokens or client secret).
    print("AUTOCLIPS_OAUTH_PREFLIGHT " + json.dumps(diagnostics), flush=True)
    dashboard.start_background_worker()
    async with mcp.session_manager.run():
        yield


# HTTP transport uses the same MCP tools as the local stdio server.
# host=0.0.0.0 avoids a restrictive localhost-only rebinding allowlist.
inner = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/app", dashboard.app_page, methods=["GET"]),
        Route("/auth/login", dashboard.login, methods=["POST"]),
        Route("/auth/logout", dashboard.logout, methods=["POST"]),
        Route("/auth/session", dashboard.session, methods=["GET"]),
        Route("/api/console/status", dashboard.status, methods=["GET"]),
        Route("/api/console/feed", dashboard.feed, methods=["GET"]),
        Route("/api/console/media/{clip_id}", dashboard.media, methods=["GET"]),
        Route("/api/console/links", dashboard.add_links, methods=["POST"]),
        Route("/api/console/upload-ready", dashboard.upload_ready, methods=["POST"]),
        Route("/api/console/sources", dashboard.sources, methods=["GET"]),
        Route("/api/console/review", dashboard.review, methods=["POST"]),
        Route("/internal/approved-demo", demo_ingest.receive_demo, methods=["POST", "GET"]),
        Route("/oauth/youtube/start", youtube_oauth_start, methods=["GET"]),
        Route("/oauth/youtube/callback", youtube_oauth_callback, methods=["GET"]),
        Route("/api/youtube/status", youtube_connection_status, methods=["GET"]),
        Route("/api/uploads", upload_media, methods=["PUT"]),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/jobs/{job_id}", status_job, methods=["GET"]),
        Mount("/", app=mcp.streamable_http_app(
            host="0.0.0.0", json_response=True, stateless_http=True,
        )),
    ],
    lifespan=lifespan,
)
app = BearerGate(inner, os.environ.get("MCP_GATEWAY_TOKEN"))
