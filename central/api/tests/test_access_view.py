"""서버 탭 '누가 · 어디로' — 금고 목록을 그룹에 맞게 걸러 보여 준다 (보기 전용)."""
import jwt
from app import inventory_source
from app.config import settings
from app.routers import access as access_router
from tests.test_auth import _proxy as _proxy_on
from tests.test_auth import _proxy_jwt, _rsa_pair

INV = {
    "dev": {
        "oci-idp": {"gw": {"host": "198.51.100.7", "port": 22},
                    "servers": {"idp-test": "192.0.2.16"},
                    "users": {"devtest": {"email": "devtest@example.local", "role": "developer",
                                          "gw_account": "devtest", "server_account": "appuser"}}},
    },
    "stg": {},
    "prod": {"shop": {"gw": {"host": "198.51.100.9"}, "servers": {"api": "192.0.2.90"}}},
}


def _oidc(monkeypatch, groups):
    priv, pub = _rsa_pair()
    monkeypatch.setattr(settings, "ct_auth_mode", "oidc")
    monkeypatch.setattr(settings, "ct_oidc_public_key", pub)
    monkeypatch.setattr(settings, "ct_oidc_issuer", "https://idp.test")
    monkeypatch.setattr(settings, "ct_oidc_audience", "controltower")
    t = jwt.encode({"email": "who@example.com", "groups": groups, "iss": "https://idp.test",
                    "aud": "controltower"}, priv, algorithm="RS256")
    return {"Authorization": f"Bearer {t}"}


def _inv(monkeypatch, data=INV):
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(access_router, "fetch_inventory", lambda: data)


def test_꺼져_있으면_off_로_빈_목록이_아니라고_알린다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_inventory_mode", "off")
    r = client.get("/api/access").json()
    assert r["state"] == "off" and r["envs"] == []


def test_못_읽으면_error_와_까닭을_보여준다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")

    def boom():
        raise inventory_source.InventoryError("AppRole 로그인 실패")
    monkeypatch.setattr(access_router, "fetch_inventory", boom)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["server-admin"])).json()
    assert r["state"] == "error" and "AppRole" in r["error"]


def test_그룹을_모르면_전부가_아니라_막고_금고도_안_읽는다(client, monkeypatch):
    """운영 모양: 앞단 Authentik 만 로그인, ControlTower 는 사용자를 모름(CT_AUTH_MODE=none) + 금고 연결 켬.
    '모른다' 를 '다 볼 수 있다' 로 보면 developer · viewer 에게도 운영 gw · 서버 주소가 간다."""
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    read: list = []
    monkeypatch.setattr(access_router, "fetch_inventory", lambda: read.append(1) or INV)
    r = client.get("/api/access").json()
    assert r["state"] == "no_identity" and r["envs"] == [] and r["people"] == []
    assert read == [], "누군지 모르는데 금고를 읽었다"
    assert "198.51.100" not in str(r) and "192.0.2" not in str(r)


def test_로컬_미리보기만_로그인_없이_전부_본다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)
    _inv(monkeypatch)
    r = client.get("/api/access").json()
    assert r["state"] == "ok" and [e["env"] for e in r["envs"]] == ["dev", "stg", "prod"]
    assert r["viewer"]["role"] == "로그인 없음(로컬 미리보기)"


def test_연결이_꺼져_있으면_누구든_off_금고는_안_읽는다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_inventory_mode", "off")
    read: list = []
    monkeypatch.setattr(access_router, "fetch_inventory", lambda: read.append(1) or INV)
    assert client.get("/api/access").json()["state"] == "off" and read == []


def test_운영자는_전부_보고_사람은_운영자와_개발자를_나눈다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["server-admin"])).json()
    assert r["state"] == "ok" and r["viewer"]["role"] == "운영자"
    assert [e["env"] for e in r["envs"]] == ["dev", "stg", "prod"]
    admin, dev = r["people"][0], r["people"][1]
    assert admin["role"] == "admin" and admin["gw_account"] == "ubuntu" and admin["server_account"] == "ubuntu"
    assert dev == {"email": "devtest@example.local", "role": "developer", "gw_account": "devtest",
                   "server_account": "appuser", "name": None, "active": None,  # 이름표 연결 전 — 이메일만
                   "where": [{"env": "dev", "service": "oci-idp"}]}
    oci = r["envs"][0]["services"][0]
    assert oci["gw"]["host"] == "198.51.100.7" and oci["servers"] == [{"name": "idp-test", "addr": "192.0.2.16"}]


def test_개발자에게는_운영이_아예_안_보인다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["developer"])).json()
    assert [e["env"] for e in r["envs"]] == ["dev", "stg"]
    assert "198.51.100.9" not in str(r) and "shop" not in str(r), "개발자 응답에 운영 목록이 섞였다"


def test_그룹이_없으면_아무것도_안_준다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["viewer"])).json()
    assert r["state"] == "denied" and r["envs"] == [] and r["people"] == []


def _proxy(monkeypatch, groups):
    # 앞단 Authentik 이 붙이는 서명된 토큰(X-authentik-jwt)
    priv, pub = _rsa_pair()
    _proxy_on(monkeypatch, pub)
    return {"X-authentik-jwt": _proxy_jwt(priv, groups=groups)}


def test_proxy_모드도_그룹대로_거른다(client, monkeypatch):
    # 운영 모양: 앞단 Authentik 이 붙인 헤더로 그룹을 안다(CT_AUTH_MODE=proxy)
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_proxy(monkeypatch, ["authentik Admins", "server-admin"])).json()
    assert r["viewer"] == {"email": "who@example.com", "role": "운영자"}
    assert [e["env"] for e in r["envs"]] == ["dev", "stg", "prod"]
    r = client.get("/api/access", headers=_proxy(monkeypatch, ["developer"])).json()
    assert [e["env"] for e in r["envs"]] == ["dev", "stg"] and "198.51.100.9" not in str(r)
    r = client.get("/api/access", headers=_proxy(monkeypatch, ["viewer"])).json()
    assert r["state"] == "denied" and r["envs"] == []


def test_proxy_모드인데_헤더가_없으면_모름으로_막고_금고도_안_읽는다(client, monkeypatch):
    # 프록시를 안 거친 요청 · 흉내 낸 값 — '그룹 없음(권한 없음)' 이 아니라 '누군지 모름'
    _, pub = _rsa_pair()
    forged, _ = _rsa_pair()
    _proxy_on(monkeypatch, pub)
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)  # 미리보기 켜도 proxy 에선 안 열림
    read: list = []
    monkeypatch.setattr(access_router, "fetch_inventory", lambda: read.append(1) or INV)
    for h in ({}, {"X-authentik-email": "who@example.com", "X-authentik-groups": "server-admin"},
              {"X-authentik-jwt": _proxy_jwt(forged, groups=["server-admin"])}):
        r = client.get("/api/access", headers=h).json()
        assert r["state"] == "no_identity" and r["envs"] == [] and r["people"] == []
    assert read == [], "누군지 모르는데 금고를 읽었다"


def test_금고_읽기는_목록만_보고_잠깐만_기억한다(monkeypatch):
    calls = []

    def fake_call(method, path, token=None, body=None):
        calls.append((method, path))
        if path == "auth/approle/login":
            return {"auth": {"client_token": "t"}}
        if method == "LIST":
            return {"data": {"keys": ["oci-idp"]}} if path.endswith("/dev") else {}
        return {"data": {"data": {"gw": {"host": "h"}}}}
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(settings, "ct_inventory_addr", "https://vault.test")
    monkeypatch.setattr(settings, "ct_inventory_role_id", "rid")
    monkeypatch.setattr(inventory_source, "_login", lambda: "t")
    monkeypatch.setattr(inventory_source, "_call", fake_call)
    inventory_source.clear_cache()
    d = inventory_source.fetch_inventory()
    assert d == {"dev": {"oci-idp": {"gw": {"host": "h"}}}, "stg": {}, "prod": {}}
    assert all(p.startswith("inventory/") for _, p in calls), f"목록 밖을 건드렸다: {calls}"
    n = len(calls)
    inventory_source.fetch_inventory()
    assert len(calls) == n, "60초 안에 또 물었다"
    inventory_source.clear_cache()


def test_role_id_는_파일에서도_읽고_비밀은_파일로만(tmp_path, monkeypatch):
    rid, sid = tmp_path / "rid", tmp_path / "sid"
    rid.write_text("role-1\n")
    sid.write_text("secret-1\n")
    seen = {}

    def fake_call(method, path, token=None, body=None):
        seen.update(body or {})
        return {"auth": {"client_token": "t"}}
    monkeypatch.setattr(settings, "ct_inventory_addr", "https://vault.test")
    monkeypatch.setattr(settings, "ct_inventory_role_id", "")
    monkeypatch.setattr(settings, "ct_inventory_role_id_file", str(rid))
    monkeypatch.setattr(settings, "ct_inventory_secret_id_file", str(sid))
    monkeypatch.setattr(inventory_source, "_call", fake_call)
    assert inventory_source._login() == "t"
    assert seen == {"role_id": "role-1", "secret_id": "secret-1"}
