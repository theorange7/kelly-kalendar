"""
HTTP-transport launcher for Kelly (NanoClaw host bridge).

Kelly's own `kelly serve` is stdio-only. NanoClaw agent containers can't spawn a
host stdio process (and must never hold the CalDAV credential, since digest auth
can't be brokered by the OneCLI proxy). So we run Kelly as a host-local HTTP MCP
server bound to loopback; the container reaches it via host.docker.internal.

Credentials are read by `kelly` from the macOS Keychain (or CALDAV_* env
fallback) — they never leave the host. Only calendar *data* crosses to the
container.

Config via env:
  KELLY_HTTP_HOST   bind address           (default 127.0.0.1 — loopback only)
  KELLY_HTTP_PORT   bind port              (default 8787)
  KELLY_HTTP_PATH   MCP endpoint path      (default /mcp)
  KELLY_HTTP_TOKEN  required bearer token  (if set, requests without a matching
                    `Authorization: Bearer <token>` get 401). Isolates this
                    server to the one agent group whose config carries the token.
"""

from __future__ import annotations

import os

import uvicorn

from kelly.credentials import load_credentials
from kelly.server import mcp

HOST = os.environ.get("KELLY_HTTP_HOST", "127.0.0.1")
PORT = int(os.environ.get("KELLY_HTTP_PORT", "8787"))
PATH = os.environ.get("KELLY_HTTP_PATH", "/mcp")


def _load_token() -> str | None:
    """Bearer token from env, or a `.kelly_http_token` file beside this script.

    The file fallback keeps the secret out of the launchd plist.
    """
    tok = os.environ.get("KELLY_HTTP_TOKEN")
    if tok:
        return tok.strip()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kelly_http_token")
    try:
        with open(path) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


TOKEN = _load_token()

_UNAUTH = b'{"error":"unauthorized"}'


def _bearer_gate(app, token: str):
    """Raw-ASGI wrapper: reject HTTP requests lacking the bearer token.

    Operates below Starlette so it survives FastMCP/Starlette internal changes,
    and forwards non-HTTP scopes (lifespan, websocket) untouched so the mounted
    app's startup/shutdown still runs.
    """
    expected = f"Bearer {token}".encode()

    async def wrapped(scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != expected:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": _UNAUTH})
                return
        await app(scope, receive, send)

    return wrapped


def main() -> None:
    # Fail fast if creds are missing, rather than 500ing on the first tool call.
    load_credentials()

    # allowed_hosts must include host.docker.internal or FastMCP's DNS-rebinding
    # guard rejects the container's requests (the Host header it sends).
    app = mcp.http_app(
        path=PATH,
        allowed_hosts=[
            "127.0.0.1",
            f"127.0.0.1:{PORT}",
            "localhost",
            f"localhost:{PORT}",
            "host.docker.internal",
            f"host.docker.internal:{PORT}",
        ],
    )

    if TOKEN:
        app = _bearer_gate(app, TOKEN)

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
