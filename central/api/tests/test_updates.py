"""업데이트 수집 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _server(client) -> int:
    client.post(
        "/api/servers/import",
        json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]},
        headers=AUTH,
    )
    return client.get("/api/servers").json()[0]["id"]


def test_snapshots_requires_auth(client):
    assert client.post("/api/updates/snapshots", json={"snapshots": []}).status_code == 401


def test_updates_flow(client):
    sid = _server(client)
    pkgs = [
        {"name": "openssl", "from": "3.0.2", "to": "3.0.13", "security": True},
        {"name": "vim", "from": "8.2", "to": "8.2.5", "security": False},
    ]
    client.post(
        "/api/updates/snapshots",
        json={"snapshots": [{"server_id": sid, "packages": pkgs}]},
        headers=AUTH,
    )
    m = client.get("/api/updates").json()
    assert len(m) == 1
    row = m[0]
    assert row["hostname"] == "web-01"
    assert row["pending"] == 2
    assert row["security"] == 1
    assert [p["name"] for p in row["packages"]] == ["openssl", "vim"]


def test_updates_upsert_and_error(client):
    sid = _server(client)
    # 1) 최초 수집(1건)
    client.post(
        "/api/updates/snapshots",
        json={"snapshots": [{"server_id": sid, "packages": [{"name": "a", "from": "1", "to": "2", "security": False}]}]},
        headers=AUTH,
    )
    # 2) 재수집(upsert) → 행 1개 유지, 내용 갱신(0건)
    client.post("/api/updates/snapshots", json={"snapshots": [{"server_id": sid, "packages": []}]}, headers=AUTH)
    m = client.get("/api/updates").json()
    assert len(m) == 1 and m[0]["pending"] == 0

    # 3) 수집 실패 → error 표시
    client.post(
        "/api/updates/snapshots",
        json={"snapshots": [{"server_id": sid, "packages": None, "error": "timeout"}]},
        headers=AUTH,
    )
    row = client.get("/api/updates").json()[0]
    assert row["error"] == "timeout" and row["pending"] == 0
