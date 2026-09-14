"""서버 그룹·태그 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _server(client) -> int:
    client.post("/api/servers/import", json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]}, headers=AUTH)
    return client.get("/api/servers").json()[0]["id"]


def test_create_group_and_assign(client):
    sid = _server(client)
    gid = client.post("/api/groups", json={"name": "prod"}).json()["id"]
    r = client.post(f"/api/servers/{sid}/meta", json={"group_id": gid, "tags": ["edge", "nginx"]})
    assert r.status_code == 200
    s = client.get("/api/servers").json()[0]
    assert s["group"] == "prod" and s["group_id"] == gid
    assert s["tags"] == ["edge", "nginx"]
    assert client.get("/api/groups").json() == [{"id": gid, "name": "prod", "count": 1}]


def test_group_name_dedup(client):
    a = client.post("/api/groups", json={"name": "prod"}).json()["id"]
    b = client.post("/api/groups", json={"name": "prod"}).json()["id"]
    assert a == b


def test_tags_only_does_not_touch_group(client):
    sid = _server(client)
    gid = client.post("/api/groups", json={"name": "prod"}).json()["id"]
    client.post(f"/api/servers/{sid}/meta", json={"group_id": gid})
    client.post(f"/api/servers/{sid}/meta", json={"tags": ["a", "b"]})  # 태그만 → 그룹 유지
    s = client.get("/api/servers").json()[0]
    assert s["group_id"] == gid and s["tags"] == ["a", "b"]


def test_clear_group_and_validation(client):
    sid = _server(client)
    gid = client.post("/api/groups", json={"name": "prod"}).json()["id"]
    client.post(f"/api/servers/{sid}/meta", json={"group_id": gid})
    client.post(f"/api/servers/{sid}/meta", json={"group_id": None})  # 해제
    assert client.get("/api/servers").json()[0]["group"] is None
    assert client.post(f"/api/servers/{sid}/meta", json={"group_id": 9999}).status_code == 400
    assert client.post("/api/servers/9999/meta", json={"tags": ["x"]}).status_code == 404
