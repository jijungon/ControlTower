"""Phase 0 API 스모크 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}  # settings.ct_api_token 기본값


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # 배포 확인용 version/build 필드가 항상 있어야 한다(기본값 'dev')
    assert "version" in body and "build" in body


def test_version_for_screen(client):
    # 화면 맨 위 버전 — 화면(nginx)은 /api 만 넘기므로 /api/version 으로 닿아야 한다. 안 넣었으면 'dev'(지어내지 않음)
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "dev" and body["build"] == "dev"
    assert body["started_at"].endswith("+00:00")  # 이 API 가 뜬 시각(UTC)


def test_list_servers_empty(client):
    r = client.get("/api/servers")
    assert r.status_code == 200
    assert r.json() == []


def test_post_connection_tests(client):
    payload = {"results": [{"server_id": 1, "ok": True, "latency_ms": 12}]}
    r = client.post("/api/connection-tests", json=payload, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["accepted"] == 1


def test_post_connection_tests_validation(client):
    r = client.post("/api/connection-tests", json={"results": [{"server_id": 1}]}, headers=AUTH)
    assert r.status_code == 422


def test_connection_tests_requires_auth(client):
    r = client.post("/api/connection-tests", json={"results": []})
    assert r.status_code == 401
