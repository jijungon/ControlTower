"""GitLab repo 선언본 버전 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def test_repo_snapshots_require_auth_targets_open(client):
    # 대상 등록은 UI 액션(open), 스냅샷 업로드는 러너 토큰 필요
    assert client.post("/api/versions/repo-targets", json={"repo": "a", "project": "g/a"}).status_code == 200
    assert client.post("/api/versions/repo-snapshots", json={"snapshots": []}).status_code == 401


def test_repo_targets_upsert(client):
    client.post("/api/versions/repo-targets", json={"repo": "aggregator_web", "project": "group/aggregator_web"}, headers=AUTH)
    client.post("/api/versions/repo-targets", json={"repo": "aggregator_web", "project": "group/aggregator_web2"}, headers=AUTH)
    assert client.get("/api/versions/repo-targets").json() == [{"repo": "aggregator_web", "project": "group/aggregator_web2"}]


def test_repo_versions_in_matrix(client):
    client.post(
        "/api/versions/repo-snapshots",
        json={"snapshots": [
            {"repo": "aggregator_web", "tool": "node", "version": "20.11"},
            {"repo": "aggregator_web", "tool": "nest", "version": "10.3"},
        ]},
        headers=AUTH,
    )
    m = client.get("/api/versions").json()
    assert len(m) == 1
    row = m[0]
    assert row["kind"] == "repo"
    assert row["name"] == "aggregator_web"
    assert row["tools"] == {"node": "20.11", "nest": "10.3"}


def test_server_and_repo_unified(client):
    # 서버 툴체인 1건
    client.post("/api/servers/import", json={"servers": [{"hostname": "build-01", "ssh_user": "deploy"}]}, headers=AUTH)
    sid = client.get("/api/servers").json()[0]["id"]
    client.post("/api/versions/snapshots", json={"snapshots": [{"server_id": sid, "tool": "docker", "version": "24.0.7"}]}, headers=AUTH)
    # repo 선언본 1건
    client.post("/api/versions/repo-snapshots", json={"snapshots": [{"repo": "pnl_was", "tool": "java", "version": "17"}]}, headers=AUTH)

    m = client.get("/api/versions").json()
    kinds = {r["name"]: r["kind"] for r in m}
    assert kinds == {"build-01": "server", "pnl_was": "repo"}
    # server 가 repo 보다 먼저
    assert m[0]["kind"] == "server"
