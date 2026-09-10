"""Phase 0 API 스모크 테스트."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_servers_empty(client):
    r = client.get("/api/servers")
    assert r.status_code == 200
    assert r.json() == []


def test_post_connection_tests(client):
    payload = {"results": [{"server_id": 1, "ok": True, "latency_ms": 12}]}
    r = client.post("/api/connection-tests", json=payload)
    assert r.status_code == 200
    assert r.json()["accepted"] == 1


def test_post_connection_tests_validation(client):
    # ok 는 필수 — 없으면 422
    r = client.post("/api/connection-tests", json={"results": [{"server_id": 1}]})
    assert r.status_code == 422
