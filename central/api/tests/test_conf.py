"""conf 수집·드리프트 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}
PATH = "/etc/nginx/nginx.conf"


def _server(client) -> int:
    client.post(
        "/api/servers/import",
        json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]},
        headers=AUTH,
    )
    return client.get("/api/servers").json()[0]["id"]


def test_targets_add_dedup(client):
    client.post("/api/conf/targets", json={"path": PATH}, headers=AUTH)
    client.post("/api/conf/targets", json={"path": PATH}, headers=AUTH)  # 중복 무시
    assert client.get("/api/conf/targets").json() == [PATH]


def test_targets_open_snapshots_require_auth(client):
    # 대상 등록은 UI 액션(open), 스냅샷 업로드는 러너 토큰 필요
    assert client.post("/api/conf/targets", json={"path": "/x"}).status_code == 200
    assert client.post("/api/conf/snapshots", json={"snapshots": []}).status_code == 401


def test_snapshots_requires_auth(client):
    assert client.post("/api/conf/snapshots", json={"snapshots": []}).status_code == 401


def test_adopt_missing_snapshot(client):
    r = client.post("/api/conf/baselines/adopt", json={"path": "/nope", "server_id": 999}, headers=AUTH)
    assert r.status_code == 404


def test_drift_flow(client):
    sid = _server(client)
    client.post("/api/conf/targets", json={"path": PATH}, headers=AUTH)

    # 1) 스냅샷 업로드 → baseline 없음 = no_baseline
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "A"}]}, headers=AUTH)
    m = client.get("/api/conf").json()
    assert len(m) == 1 and m[0]["status"] == "no_baseline"

    # 2) 그 스냅샷을 baseline 으로 채택 → synced
    assert client.post("/api/conf/baselines/adopt", json={"path": PATH, "server_id": sid}, headers=AUTH).status_code == 200
    assert client.get("/api/conf").json()[0]["status"] == "synced"

    # 3) 서버 내용이 바뀌어 재수집 → drift
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "B"}]}, headers=AUTH)
    assert client.get("/api/conf").json()[0]["status"] == "drift"

    # 4) 읽기 실패 스냅샷 → error
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": None, "error": "No such file"}]}, headers=AUTH)
    row = client.get("/api/conf").json()[0]
    assert row["status"] == "error" and row["detail"] == "No such file"
