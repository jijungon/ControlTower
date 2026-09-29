"""로그인 어댑터 테스트 — none(기본, 익명) + oidc(정적 공개키로 JWT 검증, Authentik 없이)."""
import jwt
from app.config import settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _rsa_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


def test_me_none_mode_is_anonymous(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "email": None, "groups": []}


def test_me_oidc_valid_token(client, monkeypatch):
    priv, pub = _rsa_pair()
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    monkeypatch.setattr(settings, "ct_oidc_issuer", "https://idp.test")
    monkeypatch.setattr(settings, "ct_oidc_audience", "controltower")
    token = jwt.encode(
        {
            "email": "[email protected]",
            "groups": ["authentik-admins"],
            "iss": "https://idp.test",
            "aud": "controltower",
        },
        priv,
        algorithm="RS256",
    )
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["email"] == "[email protected]"
    assert body["groups"] == ["authentik-admins"]


def test_me_oidc_missing_token_401(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", "unused")
    r = client.get("/api/me")
    assert r.status_code == 401


def test_me_oidc_invalid_token_401(client, monkeypatch):
    _, pub = _rsa_pair()
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    r = client.get("/api/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
