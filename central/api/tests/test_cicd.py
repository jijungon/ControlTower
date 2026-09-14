"""CI/CD 현황 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def test_status_requires_auth_targets_open(client):
    # 대상 등록은 UI 액션(open), 상태 업로드는 러너 토큰 필요
    assert client.post("/api/cicd/targets", json={"service": "a", "project": "g/a"}).status_code == 200
    assert client.post("/api/cicd/status", json={"statuses": []}).status_code == 401


def test_targets_upsert(client):
    client.post("/api/cicd/targets", json={"service": "admin", "project": "group/aggregator-admin"}, headers=AUTH)
    client.post("/api/cicd/targets", json={"service": "admin", "project": "group/admin-v2"}, headers=AUTH)  # 갱신
    assert client.get("/api/cicd/targets").json() == [{"service": "admin", "project": "group/admin-v2"}]


def test_matrix_target_without_status(client):
    client.post("/api/cicd/targets", json={"service": "chat", "project": "group/chat"}, headers=AUTH)
    m = client.get("/api/cicd").json()
    assert m == [
        {
            "service": "chat",
            "project": "group/chat",
            "has_cicd": False,
            "status": None,
            "ref": None,
            "sha": None,
            "web_url": None,
            "collected_at": None,
        }
    ]


def test_status_upsert_and_join(client):
    client.post("/api/cicd/targets", json={"service": "chat", "project": "group/chat"}, headers=AUTH)
    client.post(
        "/api/cicd/status",
        json={"statuses": [{"service": "chat", "has_cicd": True, "status": "success", "ref": "main", "sha": "abc", "web_url": "http://gl/p/1"}]},
        headers=AUTH,
    )
    row = client.get("/api/cicd").json()[0]
    assert row["has_cicd"] is True and row["status"] == "success" and row["ref"] == "main"
    # 재업로드 → upsert(실패로 갱신)
    client.post("/api/cicd/status", json={"statuses": [{"service": "chat", "has_cicd": True, "status": "failed"}]}, headers=AUTH)
    assert client.get("/api/cicd").json()[0]["status"] == "failed"


def test_status_service_without_target(client):
    client.post("/api/cicd/status", json={"statuses": [{"service": "solo", "has_cicd": True, "status": "failed"}]}, headers=AUTH)
    m = client.get("/api/cicd").json()
    assert len(m) == 1 and m[0]["service"] == "solo" and m[0]["project"] is None
