"""작업이력 / 감사 로그 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def test_audit_read_is_open(client):
    assert client.get("/api/audit").status_code == 200  # 읽기는 인증 불필요


def test_audit_records_runner_actions(client):
    client.post(
        "/api/servers/import",
        json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]},
        headers=AUTH,
    )
    sid = client.get("/api/servers").json()[0]["id"]
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": "/etc/x", "content": "A"}]}, headers=AUTH)
    client.post("/api/updates/snapshots", json={"snapshots": [{"server_id": sid, "packages": []}]}, headers=AUTH)

    audit = client.get("/api/audit").json()
    actions = [a["action"] for a in audit]
    assert actions[0] == "updates.collect"          # 최신순
    assert "server.import" in actions
    assert "conf.collect" in actions
    assert all(a["actor"] == "runner" and a["created_at"] for a in audit)


def test_audit_conn_test_recorded(client):
    client.post(
        "/api/servers/import",
        json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]},
        headers=AUTH,
    )
    sid = client.get("/api/servers").json()[0]["id"]
    client.post("/api/connection-tests", json={"results": [{"server_id": sid, "ok": True}]}, headers=AUTH)
    row = next(a for a in client.get("/api/audit").json() if a["action"] == "conn.test")
    assert row["detail"] == "1/1 OK"


def test_audit_paging_offset_and_total(client):
    for i in range(3):
        client.post("/api/servers/import", json={"servers": [{"hostname": f"web-0{i}", "ssh_user": "deploy"}]}, headers=AUTH)
    full = client.get("/api/audit").json()
    r = client.get("/api/audit", params={"limit": 2, "offset": 1})
    assert r.headers["X-Total-Count"] == str(len(full))  # 전체 건수 — 화면 '1–10 / N'
    assert [a["id"] for a in r.json()] == [a["id"] for a in full[1:3]]  # 최신순에서 1 건 건너뛰고 2 건
