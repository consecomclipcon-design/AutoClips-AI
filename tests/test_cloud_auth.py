import asyncio
import pytest
from autoclips.cloud_auth import BearerGate

async def make_call(gate, path, authorization=None, request_type="http"):
    sent = []
    async def receive():
        return {"type":"http.request", "body":b"", "more_body":False}
    async def send(message):
        sent.append(message)
    scope = {"type":request_type,"path":path, "headers": []}
    if authorization is not None:
        scope["headers"].append((b"authorization", authorization.encode()))
    await gate(scope, receive, send)
    return sent

async def downstream(scope,receive,send):
    await send({"type":"http.response.start", "status":200, "headers":[]})
    await send({"type":"http.response.body", "body":b"ok"})

TOKEN = "a" * 40

def test_secret_required():
    for token in (None, "", "password", "changeme"):
        with pytest.raises(ValueError):
            BearerGate(downstream,token)

@pytest.mark.parametrize("path",["/mcp", "/mcp/", "/projects", "/config"])
def test_public_endpoint_denied(path):
    gate=BearerGate(downstream,TOKEN)
    response=asyncio.run(make_call(gate,path))
    assert response[0]["status"]==401

def test_authorized_request():
    gate=BearerGate(downstream,TOKEN)
    response=asyncio.run(make_call(gate, "/mcp",f"Bearer {TOKEN}"))
    assert response[0]["status"]==200

def test_wrong_token_denied():
    gate=BearerGate(downstream,TOKEN)
    response=asyncio.run(make_call(gate, "/mcp",f"Bearer {TOKEN[:-1]}x"))
    assert response[0]["status"]==401

def test_public_health_only():
    gate=BearerGate(downstream,TOKEN)
    response=asyncio.run(make_call(gate,"/health"))
    assert response[0]["status"]==200
    response=asyncio.run(make_call(gate,"/health/not"))
    assert response[0]["status"]==401
