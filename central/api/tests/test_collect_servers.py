"""도장 길(#58) — 수집기가 읽을 서버의 주소를 중앙이 금고 목록에서 찾아 준다(GET /api/collect/servers).

수집기 신분(ct-collector)은 목록을 못 읽는다 → 중앙(ct-inventory)이 대신. 물은 이름만, 이름 · 주소만.
"""
from app import inventory_source
from app.config import settings
from app.routers import collect as collect_router

AUTH = {"Authorization": "Bearer dev-runner-token"}
INV = {
    "dev": {
        "shop": {
            "gw": {"host": "gw.example.internal", "port": 22},
            "servers": {"web-01": "192.0.2.10", "web-02": "192.0.2.11"},
            "users": {"devtest": {"email": "dev@example.com", "role": "developer"}},
        },
    },
    "stg": {},
    "prod": {"shop": {"servers": {"web-01": "198.51.100.10"}}},
}


def _inv(monkeypatch, data=INV):
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(collect_router, "fetch_inventory", lambda: data)


def test_러너_토큰이_있어야_한다(client):
    assert client.get("/api/collect/servers", params={"pick": ["dev/shop/web-01"]}).status_code == 401


def test_물은_이름만_주소와_함께_주고_못_찾은_것은_missing(client, monkeypatch):
    _inv(monkeypatch)
    r = client.get(
        "/api/collect/servers",
        params={"pick": ["dev/shop/web-01", "prod/shop/web-01", "dev/shop/없는서버", "qa/shop/web-01", "dev/shop"]},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ok"  # 입력(가짜 목록)을 실제로 읽었는지 먼저
    assert body["servers"] == [
        {"env": "dev", "service": "shop", "name": "web-01", "addr": "192.0.2.10"},
        {"env": "prod", "service": "shop", "name": "web-01", "addr": "198.51.100.10"},
    ]
    assert body["missing"] == ["dev/shop/없는서버", "qa/shop/web-01", "dev/shop"]  # 추측하지 않음
    # 사람(users · 이메일) · gw · 묻지 않은 서버는 안 준다
    assert "dev@example.com" not in r.text and "devtest" not in r.text and "gw.example" not in r.text
    assert "192.0.2.11" not in r.text


def test_이름을_안_주면_아무것도_안_준다(client, monkeypatch):
    _inv(monkeypatch)
    body = client.get("/api/collect/servers", headers=AUTH).json()
    assert body == {"state": "ok", "servers": [], "missing": []}


def test_금고_연결이_꺼져_있으면_off(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_inventory_mode", "off")
    body = client.get("/api/collect/servers", params={"pick": ["dev/shop/web-01"]}, headers=AUTH).json()
    assert body == {"state": "off", "servers": [], "missing": ["dev/shop/web-01"]}


def test_목록을_못_읽으면_error_와_까닭(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")

    def boom():
        raise inventory_source.InventoryError("AppRole 로그인 실패 — secret_id 만료가 가장 흔하다")
    monkeypatch.setattr(collect_router, "fetch_inventory", boom)
    body = client.get("/api/collect/servers", params={"pick": ["dev/shop/web-01"]}, headers=AUTH).json()
    assert body["state"] == "error" and "AppRole" in body["error"] and body["servers"] == []
