"""버전(툴체인) 수집 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _server(client) -> int:
    client.post(
        "/api/servers/import",
        json={"servers": [{"hostname": "build-01", "ssh_user": "deploy"}]},
        headers=AUTH,
    )
    return client.get("/api/servers").json()[0]["id"]


def test_snapshots_requires_auth(client):
    assert client.post("/api/versions/snapshots", json={"snapshots": []}).status_code == 401


def test_versions_matrix(client):
    sid = _server(client)
    client.post(
        "/api/versions/snapshots",
        json={"snapshots": [
            {"server_id": sid, "tool": "node", "version": "20.11.1"},
            {"server_id": sid, "tool": "java", "version": "17.0.9"},
        ]},
        headers=AUTH,
    )
    m = client.get("/api/versions").json()
    assert len(m) == 1
    assert m[0]["name"] == "build-01"
    assert m[0]["kind"] == "server"
    assert m[0]["tools"] == {"node": "20.11.1", "java": "17.0.9"}


def test_versions_upsert(client):
    sid = _server(client)
    client.post("/api/versions/snapshots", json={"snapshots": [{"server_id": sid, "tool": "node", "version": "18.19.0"}]}, headers=AUTH)
    client.post("/api/versions/snapshots", json={"snapshots": [{"server_id": sid, "tool": "node", "version": "20.11.1"}]}, headers=AUTH)
    m = client.get("/api/versions").json()
    assert m[0]["tools"]["node"] == "20.11.1"  # 최신으로 갱신
