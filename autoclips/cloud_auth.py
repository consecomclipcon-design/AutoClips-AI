"""Single-owner bearer-token gate for the deployment's HTTP endpoints.

This is a transitional control for direct API/MCP clients. It is NOT an OAuth
2.1 authorization server and therefore does not by itself make the app a
ChatGPT custom MCP connector.
"""
from __future__ import annotations

import hmac


class BearerGate:
    def __init__(self, app, token: str | None):
        if not token or len(token) < 32 or token.lower() in {"changeme", "password"}:
            raise ValueError("MCP_GATEWAY_TOKEN precisa conter pelo menos 32 caracteres aleatórios")
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") != "/health":
            auths = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            expected = f"Bearer {self.token}".encode("utf-8")
            allowed = len(auths) == 1 and hmac.compare_digest(auths[0], expected)
            if not allowed:
                body = b'{"error":"unauthorized"}'
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ]})
                await send({"type": "http.response.body", "body": body})
                return
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)
