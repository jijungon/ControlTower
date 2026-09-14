"""conf 적용(plan→approve→apply) 상태머신 테스트. (PR-A: 서버 쓰기 없음)"""

AUTH = {"Authorization": "Bearer dev-runner-token"}
PATH = "/etc/nginx/nginx.conf"


def _server(client) -> int:
    client.post("/api/servers/import", json={"servers": [{"hostname": "web-01", "ssh_user": "deploy"}]}, headers=AUTH)
    return client.get("/api/servers").json()[0]["id"]


def _drift(client) -> int:
    """web-01 에 드리프트 상황 구성(기준본 A, 실제본 B) → server_id."""
    sid = _server(client)
    client.post("/api/conf/targets", json={"path": PATH}, headers=AUTH)
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "A\n"}]}, headers=AUTH)
    client.post("/api/conf/baselines/adopt", json={"path": PATH, "server_id": sid}, headers=AUTH)  # baseline=A → synced
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "B\n"}]}, headers=AUTH)  # drift
    return sid


def test_plan_creates_pending_with_diff(client):
    sid = _drift(client)
    r = client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH})
    assert r.status_code == 200, r.text
    it = r.json()
    assert it["status"] == "pending"
    assert "A" in it["diff"] and "B" in it["diff"]  # current(B) → baseline(A)


def test_plan_requires_drift(client):
    sid = _server(client)
    client.post("/api/conf/targets", json={"path": PATH}, headers=AUTH)
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "A\n"}]}, headers=AUTH)
    client.post("/api/conf/baselines/adopt", json={"path": PATH, "server_id": sid}, headers=AUTH)  # synced
    assert client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).status_code == 400


def test_plan_requires_baseline(client):
    sid = _server(client)
    client.post("/api/conf/snapshots", json={"snapshots": [{"server_id": sid, "path": PATH, "content": "B\n"}]}, headers=AUTH)
    assert client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).status_code == 400


def test_approve_gate(client):
    sid = _drift(client)
    iid = client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).json()["id"]
    assert client.post(f"/api/conf/apply/{iid}/approve").json()["status"] == "approved"
    # 이미 approved → 재승인 불가
    assert client.post(f"/api/conf/apply/{iid}/approve").status_code == 409


def test_cancel(client):
    sid = _drift(client)
    iid = client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).json()["id"]
    assert client.post(f"/api/conf/apply/{iid}/cancel").json()["status"] == "canceled"


def test_result_requires_auth_and_approved(client):
    sid = _drift(client)
    iid = client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).json()["id"]
    # 인증 필요
    assert client.post(f"/api/conf/apply/{iid}/result", json={"status": "applied"}).status_code == 401
    # pending 상태에서는 적용 결과 불가(approved 만)
    assert client.post(f"/api/conf/apply/{iid}/result", json={"status": "applied"}, headers=AUTH).status_code == 409
    # 승인 후 결과 보고 OK
    client.post(f"/api/conf/apply/{iid}/approve")
    r = client.post(f"/api/conf/apply/{iid}/result", json={"status": "applied", "backup_path": "/tmp/x.bak"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "applied"


def test_list_and_filter(client):
    sid = _drift(client)
    iid = client.post("/api/conf/apply/plan", json={"server_id": sid, "path": PATH}).json()["id"]
    assert len(client.get("/api/conf/apply").json()) == 1
    assert client.get("/api/conf/apply?status=approved").json() == []
    client.post(f"/api/conf/apply/{iid}/approve")
    approved = client.get("/api/conf/apply?status=approved").json()
    assert len(approved) == 1 and approved[0]["id"] == iid
