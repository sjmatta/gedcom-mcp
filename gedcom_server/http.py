"""Authenticated Streamable HTTP entry point for a Cloudflare Tunnel origin."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import jwt
import uvicorn
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class AccessVerifier:
    """Accept only Cloudflare-signed, unexpired tokens for this Access application."""

    def __init__(self, team_domain: str, audience: str):
        parsed = urlsplit(team_domain)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".cloudflareaccess.com")
            or parsed.netloc != parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not audience
        ):
            raise ValueError("A Cloudflare Access team HTTPS origin and audience are required")
        self.issuer = team_domain.rstrip("/")
        self.audience = audience
        self.jwks = jwt.PyJWKClient(self.issuer + "/cdn-cgi/access/certs", timeout=5)

    def verify(self, assertion: str) -> bool:
        try:
            key = self.jwks.get_signing_key_from_jwt(assertion)
            jwt.decode(
                assertion,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            return True
        except (jwt.PyJWTError, ValueError):
            return False


class AccessGate:
    def __init__(self, app: ASGIApp, verifier: AccessVerifier, allowed_hosts: set[str]):
        self.app = app
        self.verifier = verifier
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = dict(scope.get("headers", []))
        if headers.get(b"host", b"").decode("ascii", errors="replace") not in self.allowed_hosts:
            response = JSONResponse({"error": "Invalid host"}, status_code=421)
        elif b"origin" in headers:
            response = JSONResponse({"error": "Browser origins are not allowed"}, status_code=403)
        elif scope["path"] == "/healthz" and scope["method"] == "GET":
            response = JSONResponse({"status": "ok"})
        else:
            assertion = headers.get(b"cf-access-jwt-assertion", b"").decode(
                "ascii", errors="replace"
            )
            if assertion and await asyncio.to_thread(self.verifier.verify, assertion):
                return await self.app(scope, receive, send)
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
        await response(scope, receive, send)


def build_app() -> AccessGate:
    # Configuration must exist and validate before any genealogy data is loaded.
    config = json.loads(Path(os.environ["CF_ACCESS_CONFIG_FILE"]).read_text())
    verifier = AccessVerifier(config["team_domain"], config["audience"])
    from . import initialize, mcp

    initialize()
    hosts = set(os.getenv("MCP_ALLOWED_HOSTS", "localhost:8768,127.0.0.1:8768").split(","))
    app = mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        host_origin_protection=True,
        allowed_hosts=list(hosts),
        allowed_origins=[],
    )
    return AccessGate(app, verifier, hosts)


def main():
    uvicorn.run(build_app(), host="0.0.0.0", port=8768, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
