"""개발자(server-admin 아님)는 서버 탭만 — 화면만 숨기지 않고 API 도 403. 그룹을 아는 모드(oidc · proxy)에서만."""
import jwt
from app.config import settings
from tests.test_auth import ISS, _proxy, _proxy_jwt, _rsa_pair

RUNNER = {"Authorization": "Bearer dev-runner-token"}  # settings.ct_api_token 기본값
OPEN = ["/api/me", "/api/access", "/api/version"]
IMPORT = {"servers": [{"hostname": "web-01", "ip": "10.0.0.1", "ssh_user": "deploy", "credential_alias": "id_rsa"}]}


def _as(monkeypatch, groups):
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    return {"X-authentik-jwt": _proxy_jwt(priv, groups=groups)}


def test_개발자는_서버_탭_API_말고는_읽기도_쓰기도_403(client, monkeypatch):
    h = _as(monkeypatch, ["developer"])
    for path in ("/api/servers", "/api/cicd/shape", "/api/conf", "/api/audit", "/api/servers/"):
        r = client.get(path, headers=h)
        assert r.status_code == 403, path
        assert r.json() == {"detail": "개발자는 서버 탭만 볼 수 있어요"}
    assert client.post("/api/groups", json={"name": "x"}, headers=h).status_code == 403
    assert client.get("/api/no-such-api-yet", headers=h).status_code == 403  # 새로 생길 API 도 기본 막힘


def test_개발자도_서버_탭이_쓰는_넷은_열림(client, monkeypatch):
    h = _as(monkeypatch, ["developer"])
    for path in OPEN:
        assert client.get(path, headers=h).status_code == 200, path


def test_IdP_서버_상태줄은_운영자만_개발자는_403(client, monkeypatch):
    """맨 위 IdP 서버 상태줄(서버 이름 · 문제)은 운영자만(10-28) — 화면만 숨기지 않고 API 도 403."""
    status = {"source": "idp", "read_ok": True, "written_at": "2026-10-28T00:00:00+00:00", "host": "idp-host.example.local",
              "ok": False, "problems": ["openbao sealed"]}
    dev = _as(monkeypatch, ["developer"])
    # 수집기(러너 공유 토큰)는 개발자 문지기와 상관없이 그대로 올린다
    assert client.post("/api/host-status", json=status, headers=RUNNER).json() == {"ok": True}
    r = client.get("/api/host-status", headers=dev)
    assert r.status_code == 403 and r.json() == {"detail": "개발자는 서버 탭만 볼 수 있어요"}
    assert "idp-host" not in r.text and "openbao" not in r.text
    for groups in (["server-admin"], ["developer", "server-admin"]):
        r = client.get("/api/host-status", headers=_as(monkeypatch, groups))
        assert r.status_code == 200 and r.json()[0]["host"] == "idp-host.example.local", groups


def test_운영자_둘다_viewer_신분증없음은_지금처럼(client, monkeypatch):
    for groups in (["server-admin"], ["developer", "server-admin"], ["viewer"]):
        h = _as(monkeypatch, groups)
        assert client.get("/api/servers", headers=h).status_code == 200, groups
    _as(monkeypatch, ["developer"])
    assert client.get("/api/servers").status_code == 200  # 토큰 없음 = 익명 — 각 API 가 지금처럼


def test_러너_공유_토큰_길은_그대로(client, monkeypatch):
    _as(monkeypatch, ["developer"])
    assert client.post("/api/servers/import", json=IMPORT, headers=RUNNER).status_code == 200
    # oidc 모드에서도 러너 토큰(JWT 아님)은 신분증 오류로 빠져서 그대로 닿는다
    _, pub = _rsa_pair()
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    assert client.post("/api/servers/import", json=IMPORT, headers=RUNNER).status_code == 200


def test_none_모드에서는_개발자_토큰이_와도_전부_열림(client, monkeypatch):
    h = _as(monkeypatch, ["developer"])
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    assert client.get("/api/servers", headers=h).status_code == 200


def test_oidc_모드_개발자도_403(client, monkeypatch):
    priv, pub = _rsa_pair()
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    monkeypatch.setattr(settings, "ct_oidc_issuer", ISS)
    monkeypatch.setattr(settings, "ct_oidc_audience", "")
    t = jwt.encode({"email": "dev@example.com", "groups": ["developer"], "iss": ISS}, priv, algorithm="RS256")
    h = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/servers", headers=h).status_code == 403
    assert client.get("/api/me", headers=h).status_code == 200
