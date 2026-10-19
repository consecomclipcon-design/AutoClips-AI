"""HTTP transport for Railway and other trusted, one-owner deployments.

Every endpoint except /health requires MCP_GATEWAY_TOKEN (64+ recommended).
This gateway is not OAuth 2.1. Direct ChatGPT custom MCP installation needs
an OIDC/OAuth authorization provider; do not advertise this as ChatGPT-ready.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from autoclips.cloud_auth import BearerGate
from autoclips.upload_http import upload_media
from autoclips.api_http import create_project, status_job
from server import mcp


async def health(request):
    return JSONResponse({"status": "ok", "service": "autoclips-ai", "mode": "private-mcp"})


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


# HTTP transport uses the same MCP tools as the local stdio server.
# host=0.0.0.0 avoids a restrictive localhost-only rebinding allowlist.
inner = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
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
