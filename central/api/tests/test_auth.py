"""로그인 어댑터 테스트 — none(기본, 익명) + oidc · proxy(정적 공개키로 JWT 검증, Authentik 없이)."""
import time

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



ISS = "https://idp.test/application/o/controltower/"


def _proxy(monkeypatch, pub: str, audience: str = "") -> None:
    monkeypatch.setattr(settings, "ct_auth_mode", "proxy")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    monkeypatch.setattr(settings, "ct_oidc_issuer", ISS)
    monkeypatch.setattr(settings, "ct_oidc_audience", audience)


def _proxy_jwt(priv: str, **over) -> str:
    claims = {"email": "who@example.com", "groups": ["developer", "viewer"], "iss": ISS,
              "exp": int(time.time()) + 300}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, priv, algorithm="RS256")


def test_me_proxy_reads_signed_authentik_jwt(client, monkeypatch):
    # 앞단 Authentik 이 붙이는 X-authentik-jwt — 서명이 맞으면 그 안의 이메일 · 그룹
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    r = client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(priv)}).json()
    assert {k: r[k] for k in ("authenticated", "email", "groups")} == {
        "authenticated": True, "email": "who@example.com", "groups": ["developer", "viewer"]}


def test_me_proxy_does_not_trust_plain_headers(client, monkeypatch):
    # 글자 헤더는 누구나 흉내 낼 수 있다 — 토큰이 없으면 익명(401 아님)
    _, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    anon = {"authenticated": False, "email": None, "groups": []}
    no_token = {"token": False, "ok": False, "reason": "X-authentik-jwt 없음 — 앞단 Authentik 을 안 거쳤거나 붙이지 않음"}
    assert client.get("/api/me").json() == {**anon, "proxy": no_token}
    h = {"X-authentik-email": "who@example.com", "X-authentik-groups": "server-admin"}
    assert client.get("/api/me", headers=h).json() == {**anon, "proxy": no_token}


def test_me_proxy_rejects_bad_tokens(client, monkeypatch):
    # 흉내 낸 서명 · HS256 · 만료 · 만료 없음 · 다른 앱(issuer) · 다른 audience · 이메일 없음 → 모두 익명
    priv, pub = _rsa_pair()
    other_priv, _ = _rsa_pair()
    _proxy(monkeypatch, pub, audience="ct-client")
    bad = [
        _proxy_jwt(other_priv, aud="ct-client"),
        jwt.encode({"email": "who@example.com", "groups": ["server-admin"], "iss": ISS, "aud": "ct-client",
                    "exp": int(time.time()) + 300}, "s" * 32, algorithm="HS256"),  # 공유 비밀(지금 운영 설정)
        _proxy_jwt(priv, aud="ct-client", exp=int(time.time()) - 60),
        _proxy_jwt(priv, aud="ct-client", exp=None),
        _proxy_jwt(priv, aud="ct-client", iss="https://idp.test/application/o/other-app/"),
        _proxy_jwt(priv, aud="other-client"),
        _proxy_jwt(priv, aud="ct-client", email=None),
        "not.a.jwt",
    ]
    for t in bad:
        assert client.get("/api/me", headers={"X-authentik-jwt": t}).json()["authenticated"] is False, t[:40]
    ok = client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(priv, aud="ct-client")}).json()
    assert ok["authenticated"] is True


def test_me_proxy_without_issuer_is_config_error(client, monkeypatch):
    # issuer 를 안 정하면 같은 키로 서명한 다른 앱 토큰도 통과한다 → 켜진 채로 조용히 열리지 않게 500
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    monkeypatch.setattr(settings, "ct_oidc_issuer", "")
    assert client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(priv)}).status_code == 500


def test_proxy_token_ignored_in_other_modes(client, monkeypatch):
    # none 에서는 같은 헤더를 보내도 사용자로 보지 않는다(켜지 않은 곳에서 통로가 안 생김)
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    assert client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(priv)}).json()["authenticated"] is False


def test_proxy_uses_jwks_like_production(client, monkeypatch):
    # 운영은 jwks 주소로 키를 받는다 — kid 로 맞는 키를 골라 검사, 한 번 받은 목록은 기억(요청마다 안 받음)
    from app import auth

    priv, pub = _rsa_pair()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(serialization.load_pem_public_key(pub.encode()), as_dict=True)
    fetched: list = []

    def fetch(self):
        fetched.append(1)
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch)
    auth._jwks_client.cache_clear()
    _proxy(monkeypatch, "")
    monkeypatch.setattr(settings, "ct_oidc_jwks_url", "https://idp.test/application/o/controltower/jwks/")
    claims = {"email": "who@example.com", "groups": ["server-admin"], "iss": ISS, "exp": int(time.time()) + 300}
    good = jwt.encode(claims, priv, algorithm="RS256", headers={"kid": "k1"})
    unknown_kid = jwt.encode(claims, priv, algorithm="RS256", headers={"kid": "k2"})
    try:
        for _ in range(3):
            assert client.get("/api/me", headers={"X-authentik-jwt": good}).json()["groups"] == ["server-admin"]
        assert len(fetched) == 1, "요청마다 jwks 를 다시 받았다"
        assert client.get("/api/me", headers={"X-authentik-jwt": unknown_kid}).json()["authenticated"] is False
    finally:
        auth._jwks_client.cache_clear()


def test_me_proxy_shows_check_result_for_first_look(client, monkeypatch):
    # 켜기 전 운영에서 한 번 열어 본다 — 토큰이 오는지 · 그룹 클레임 이름 · aud. 토큰 자체는 안 돌려준다
    priv, pub = _rsa_pair()
    other_priv, _ = _rsa_pair()
    _proxy(monkeypatch, pub)
    t = _proxy_jwt(priv, aud="client-abc", ak_groups=["x"])
    r = client.get("/api/me", headers={"X-authentik-jwt": t}).json()
    assert r["proxy"] == {"token": True, "ok": True, "reason": None, "alg": "RS256", "iss": ISS, "aud": "client-abc",
                          "claims": ["ak_groups", "aud", "email", "exp", "groups", "iss"]}
    assert t not in str(r)
    # aud 를 잘못 넣었으면 — 떨어진 까닭과 토큰에 적힌 aud 가 보여 고칠 값을 안다
    monkeypatch.setattr(settings, "ct_oidc_audience", "wrong")
    p = client.get("/api/me", headers={"X-authentik-jwt": t}).json()["proxy"]
    assert p["ok"] is False and "audience" in p["reason"].lower() and p["aud"] == "client-abc"
    monkeypatch.setattr(settings, "ct_oidc_audience", "")
    p = client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(other_priv)}).json()
    assert p["authenticated"] is False and p["proxy"]["ok"] is False and "signature" in p["proxy"]["reason"].lower()
    p = client.get("/api/me", headers={"X-authentik-jwt": _proxy_jwt(priv, email=None)}).json()["proxy"]
    assert p["ok"] is False and p["reason"] == "토큰에 email 이 없음"
    p = client.get("/api/me", headers={"X-authentik-jwt": "not.a.jwt"}).json()["proxy"]
    assert p["token"] is True and p["ok"] is False
