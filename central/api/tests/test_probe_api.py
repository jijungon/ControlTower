"""접속 점검 결과(needs_2fa) 저장·노출 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _server(client) -> int:
    client.post("/api/servers/import", json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]}, headers=AUTH)
    return client.get("/api/servers").json()[0]["id"]


def test_needs_2fa_true(client):
    sid = _server(client)
    client.post("/api/connection-tests", json={"results": [{"server_id": sid, "ok": False, "needs_2fa": True}]}, headers=AUTH)
    s = client.get("/api/servers").json()[0]
    assert s["status"] == "offline" and s["needs_2fa"] is True


def test_needs_2fa_key_only(client):
    sid = _server(client)
    client.post("/api/connection-tests", json={"results": [{"server_id": sid, "ok": True, "needs_2fa": False}]}, headers=AUTH)
    s = client.get("/api/servers").json()[0]
    assert s["status"] == "online" and s["needs_2fa"] is False


def test_needs_2fa_default_null(client):
    _server(client)
    assert client.get("/api/servers").json()[0]["needs_2fa"] is None  # 미확인
