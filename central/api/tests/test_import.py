"""서버 인벤토리 임포트 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def test_import_and_list(client):
    payload = {
        "servers": [
            {
                "hostname": "web-01",
                "ip": "10.0.1.10",
                "ssh_user": "deploy",
                "ssh_port": 2222,
                "gateway_alias": "bastion",
                "credential_alias": "svc_ed25519",
                "access_control": "ncloud",
            }
        ]
    }
    r = client.post("/api/servers/import", json=payload, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["imported_new"] == 1

    rows = client.get("/api/servers").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["hostname"] == "web-01"
    assert row["ip"] == "10.0.1.10"
    assert row["access_method"] == "via_gateway"
    assert row["credential_alias"] == "svc_ed25519"
    assert row["access_control"] == "ncloud"


def test_import_upsert(client):
    base = {"hostname": "h1", "ssh_user": "a"}
    client.post("/api/servers/import", json={"servers": [base]}, headers=AUTH)
    # 같은 hostname 재임포트 → 신규 0, user 갱신
    r = client.post("/api/servers/import", json={"servers": [{**base, "ssh_user": "b"}]}, headers=AUTH)
    assert r.json()["imported_new"] == 0
    rows = client.get("/api/servers").json()
    assert len(rows) == 1
    assert rows[0]["ssh_user"] == "b"


def test_import_requires_auth(client):
    r = client.post("/api/servers/import", json={"servers": []})
    assert r.status_code == 401


def test_connection_test_updates_status(client):
    client.post("/api/servers/import", json={"servers": [{"hostname": "s1", "ssh_user": "a"}]}, headers=AUTH)
    sid = client.get("/api/servers").json()[0]["id"]

    client.post("/api/connection-tests", json={"results": [{"server_id": sid, "ok": True, "latency_ms": 5}]}, headers=AUTH)
    row = client.get("/api/servers").json()[0]
    assert row["status"] == "online"
    assert row["last_checked_at"] is not None

    client.post("/api/connection-tests", json={"results": [{"server_id": sid, "ok": False, "error": "x"}]}, headers=AUTH)
    assert client.get("/api/servers").json()[0]["status"] == "offline"
