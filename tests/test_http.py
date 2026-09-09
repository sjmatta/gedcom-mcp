"""Regression tests for the public-origin authentication boundary."""

import time
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gedcom_server.http import AccessGate, AccessVerifier


@pytest.fixture
def verifier_and_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessVerifier("https://example.cloudflareaccess.com", "gedcom-audience")
    verifier.jwks = Mock()
    verifier.jwks.get_signing_key_from_jwt.return_value.key = key.public_key()
    return verifier, key


def token(key, **overrides):
    claims = {
        "iss": "https://example.cloudflareaccess.com",
        "aud": "gedcom-audience",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "sub": "owner",
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-app"},
        {"iss": "https://attacker.example"},
        {"exp": int(time.time()) - 60},
        {"iat": int(time.time()) + 3600},
    ],
)
def test_rejects_invalid_claims(verifier_and_key, overrides):
    verifier, key = verifier_and_key
    assert not verifier.verify(token(key, **overrides))


def test_rejects_bad_signatures_and_missing_claims(verifier_and_key):
    verifier, key = verifier_and_key
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not verifier.verify(token(other))
    assert not verifier.verify(jwt.encode({"sub": "owner"}, key, algorithm="RS256"))
    assert not verifier.verify("not-a-jwt")


def test_gate_requires_signed_access_assertion(verifier_and_key):
    verifier, key = verifier_and_key
    app = Starlette(routes=[Route("/mcp", lambda request: JSONResponse({"private": True}))])
    with TestClient(
        AccessGate(app, verifier, {"localhost:8768"}), base_url="http://localhost:8768"
    ) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/mcp").status_code == 401
        assert client.get("/mcp", headers={"Authorization": "Bearer arbitrary"}).status_code == 401
        assert client.get("/mcp", headers={"Cf-Access-Jwt-Assertion": "forged"}).status_code == 401
        headers = {"Cf-Access-Jwt-Assertion": token(key)}
        assert client.get("/mcp", headers=headers).json() == {"private": True}
        assert client.get("/mcp", headers={**headers, "Host": "evil.example"}).status_code == 421
        assert (
            client.get("/mcp", headers={**headers, "Origin": "https://evil.example"}).status_code
            == 403
        )


@pytest.mark.parametrize(
    "issuer",
    [
        "http://example.cloudflareaccess.com",
        "https://evil.example",
        "https://example.cloudflareaccess.com@evil.example",
        "https://example.cloudflareaccess.com/path",
    ],
)
def test_rejects_invalid_config(issuer):
    with pytest.raises(ValueError):
        AccessVerifier(issuer, "audience")
