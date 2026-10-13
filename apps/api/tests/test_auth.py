"""JWT verification and /me. Tokens are signed with a locally generated
RSA key; the JWKS lookup is patched so no network is involved."""

import datetime
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.main import create_app

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
ISSUER = "https://test-issuer.clerk.local"

client = TestClient(create_app())


def make_token(**overrides: Any) -> str:
    now = datetime.datetime.now(datetime.UTC)
    claims: dict[str, Any] = {
        "sub": "user_2abcDEF",
        "iss": ISSUER,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _patch_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "_get_signing_key", lambda token: PUBLIC_KEY)


def test_no_token_401() -> None:
    resp = client.get("/me")
    assert resp.status_code == 401


def test_expired_token_401() -> None:
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    resp = client.get("/me", headers={"Authorization": f"Bearer {make_token(exp=past)}"})
    assert resp.status_code == 401
    assert "ExpiredSignature" in resp.json()["detail"]


def test_wrong_issuer_401() -> None:
    resp = client.get(
        "/me",
        headers={"Authorization": f"Bearer {make_token(iss='https://evil.example')}"},
    )
    assert resp.status_code == 401


def test_valid_token_unprovisioned_403(clean_users: None) -> None:
    resp = client.get("/me", headers={"Authorization": f"Bearer {make_token()}"})
    assert resp.status_code == 403
    assert "webhook" in resp.json()["detail"].lower()


def test_valid_token_with_email_claim_jit_provisions(clean_users: None) -> None:
    token = make_token(email="colin@example.com")
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "colin@example.com"
    assert body["plan"] == "free"

    # Second call resolves the same row, not a duplicate
    resp2 = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.json()["id"] == body["id"]


def test_azp_enforced_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "http://localhost:3000")
    get_settings.cache_clear()
    try:
        bad = client.get(
            "/me",
            headers={"Authorization": f"Bearer {make_token(azp='https://evil.example')}"},
        )
        assert bad.status_code == 401
        assert "azp" in bad.json()["detail"]

        ok = client.get(
            "/me",
            headers={
                "Authorization": (
                    f"Bearer {make_token(azp='http://localhost:3000', email='a@b.co')}"
                )
            },
        )
        assert ok.status_code == 200
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
