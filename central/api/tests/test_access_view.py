"""서버 탭 '누가 · 어디로' — 금고 목록을 그룹에 맞게 걸러 보여 준다 (보기 전용)."""
import jwt
from app import inventory_source
from app.config import settings
from app.routers import access as access_router
from tests.test_auth import _rsa_pair

INV = {
    "dev": {
        "oci-idp": {"gw": {"host": "198.51.100.7", "port": 22},
                    "servers": {"idp-test": "192.0.2.16"},
                    "users": {"devtest": {"email": "devtest@example.local", "role": "developer",
                                          "gw_account": "devtest", "server_account": "appuser"}}},
    },
    "stg": {},
    "prod": {"supercycl": {"gw": {"host": "198.51.100.9"}, "servers": {"api": "192.0.2.90"}}},
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
    monkeypatch.setattr(access_router, "fetch_inventory", lambda: data)


def test_꺼져_있으면_off_로_빈_목록이_아니라고_알린다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_inventory_mode", "off")
    r = client.get("/api/access").json()
    assert r["state"] == "off" and r["envs"] == []


def test_못_읽으면_error_와_까닭을_보여준다(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")

    def boom():
        raise inventory_source.InventoryError("AppRole 로그인 실패")
    monkeypatch.setattr(access_router, "fetch_inventory", boom)
    r = client.get("/api/access").json()
    assert r["state"] == "error" and "AppRole" in r["error"]


def test_운영자는_전부_보고_사람은_운영자와_개발자를_나눈다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["server-admin"])).json()
    assert r["state"] == "ok" and r["viewer"]["role"] == "운영자"
    assert [e["env"] for e in r["envs"]] == ["dev", "stg", "prod"]
    admin, dev = r["people"][0], r["people"][1]
    assert admin["role"] == "admin" and admin["gw_account"] == "ubuntu" and admin["server_account"] == "ubuntu"
    assert dev == {"email": "devtest@example.local", "role": "developer", "gw_account": "devtest",
                   "server_account": "appuser", "where": [{"env": "dev", "service": "oci-idp"}]}
    oci = r["envs"][0]["services"][0]
    assert oci["gw"]["host"] == "198.51.100.7" and oci["servers"] == [{"name": "idp-test", "addr": "192.0.2.16"}]


def test_개발자에게는_운영이_아예_안_보인다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["developer"])).json()
    assert [e["env"] for e in r["envs"]] == ["dev", "stg"]
    assert "198.51.100.9" not in str(r) and "supercycl" not in str(r), "개발자 응답에 운영 목록이 섞였다"


def test_그룹이_없으면_아무것도_안_준다(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get("/api/access", headers=_oidc(monkeypatch, ["viewer"])).json()
    assert r["state"] == "denied" and r["envs"] == [] and r["people"] == []


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
