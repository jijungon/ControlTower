"""서비스 비교표(shape) 엔드포인트 테스트."""

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _shape(service, group="shop", env_hash="h1", **data):
    return {"service": service, "group": group, "env_hash": env_hash, "data": {"runtime": "node", "runtime_version": "18", **data}}


def test_upload_requires_runner_token(client):
    assert client.post("/api/cicd/shape", json={"shapes": []}).status_code == 401
    assert client.get("/api/cicd/shape").json() == []


def test_upload_and_list_flattens_data(client):
    deploy = {"dev": {"path": "direct", "manual": False, "mismatch": False}}
    r = client.post("/api/cicd/shape", json={"shapes": [_shape("shop web", deploy=deploy)]}, headers=AUTH)
    assert r.json() == {"accepted": 1, "removed": 0}
    row = client.get("/api/cicd/shape").json()[0]
    assert row["service"] == "shop web" and row["group"] == "shop"
    assert row["runtime"] == "node" and row["runtime_version"] == "18" and row["deploy"] == deploy
    assert row["collected_at"] and row["env_changed_at"] is None  # 첫 수집은 변경 시각 모름
    assert "env_hash" not in row  # 해시도 화면엔 안 내보냄


def test_env_changed_at_only_when_hash_changes(client):
    client.post("/api/cicd/shape", json={"shapes": [_shape("a", env_hash="h1")]}, headers=AUTH)
    client.post("/api/cicd/shape", json={"shapes": [_shape("a", env_hash="h1")]}, headers=AUTH)
    assert client.get("/api/cicd/shape").json()[0]["env_changed_at"] is None  # 같으면 그대로
    client.post("/api/cicd/shape", json={"shapes": [_shape("a", env_hash="h2")]}, headers=AUTH)
    changed = client.get("/api/cicd/shape").json()[0]["env_changed_at"]
    assert changed is not None
    client.post("/api/cicd/shape", json={"shapes": [_shape("a", env_hash=None)]}, headers=AUTH)  # 못 읽음 → 변경 아님
    assert client.get("/api/cicd/shape").json()[0]["env_changed_at"] == changed


def test_replace_drops_services_not_in_batch(client):
    client.post("/api/cicd/shape", json={"shapes": [_shape("a"), _shape("b")]}, headers=AUTH)
    r = client.post("/api/cicd/shape", json={"shapes": [_shape("a")], "replace": True}, headers=AUTH)
    assert r.json() == {"accepted": 1, "removed": 1}
    assert [s["service"] for s in client.get("/api/cicd/shape").json()] == ["a"]
    # replace 없으면 유지
    client.post("/api/cicd/shape", json={"shapes": [_shape("c")]}, headers=AUTH)
    assert {s["service"] for s in client.get("/api/cicd/shape").json()} == {"a", "c"}


def test_upload_is_audited(client):
    client.post("/api/cicd/shape", json={"shapes": [_shape("a")]}, headers=AUTH)
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "cicd.shape" in actions
