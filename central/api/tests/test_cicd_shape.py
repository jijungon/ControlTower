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


# ── center config (폴더별) ──
def _item(path, **data):
    return {"path": path, "data": {"state": "done", "start": "dockerfile", **data}}


def test_config_upload_list_and_replace(client):
    assert client.post("/api/cicd/config", json={"items": []}).status_code == 401
    r = client.post(
        "/api/cicd/config",
        json={"items": [_item("shop/web", compose={"dev": "command"}), _item("shop/was", state="base", start="base")]},
        headers=AUTH,
    )
    assert r.json() == {"accepted": 2, "removed": 0}
    rows = client.get("/api/cicd/config").json()
    assert [x["path"] for x in rows] == ["shop/was", "shop/web"]  # 경로순
    assert rows[1]["compose"] == {"dev": "command"} and rows[1]["collected_at"]
    r = client.post("/api/cicd/config", json={"items": [_item("shop/web")], "replace": True}, headers=AUTH)
    assert r.json() == {"accepted": 1, "removed": 1}
    assert [x["path"] for x in client.get("/api/cicd/config").json()] == ["shop/web"]
    assert "cicd.config" in [a["action"] for a in client.get("/api/audit").json()]


def test_new_fields_pass_through_unchanged(client):
    """러너가 늘린 값(빌드 위치·job 별 이미지·러너 이름·config repo·역할 폴더 등)은 data 안에 그대로 저장·조회 — 스키마 변경 없음."""
    ex = {"value": "shell", "guess": False, "groups": [{"tag": "b", "value": "shell", "guess": False, "why": "job 로그 #1", "jobs": ["build"], "images": {}, "runner_name": "r-01", "default_image": "x:1"}]}
    client.post("/api/cicd/shape", json={"shapes": [_shape("a web", host="github", executor_center=ex)]}, headers=AUTH)
    row = client.get("/api/cicd/shape").json()[0]
    assert row["host"] == "github" and row["executor_center"] == ex
    item = {"path": "a/manager", "data": {"state": "done", "folder": "a/web", "config_repo": "a/config", "group": "g", "deploy_envs": ["dev"],
                                          "compose_miss": {"prod": {"state": "fail", "reason": "x"}}}}
    client.post("/api/cicd/config", json={"items": [item]}, headers=AUTH)
    got = client.get("/api/cicd/config").json()[0]
    assert {k: got[k] for k in ("folder", "config_repo", "group", "deploy_envs", "compose_miss")} == {k: item["data"][k] for k in ("folder", "config_repo", "group", "deploy_envs", "compose_miss")}


def test_versions_and_repo_pass_through(client):
    """빌드·배포 버전(환경별 tag)과 repo 정보는 data 안에 그대로 저장·반환 — 새 칸이라도 DB 모양은 안 바뀜."""
    versions = {
        "build": {"prod": {"version": "v1.0.9", "tag": "prod-was-v1.0.9", "at": "2026-10-13T10:52:00Z", "job": 40, "side": "center"}},
        "deploy": {"prod": {"version": "v1.0.2", "tag": "prod-was-v1.0.2", "at": "2026-10-01T14:23:00Z", "job": 30, "side": "center"}},
    }
    repo = {"project": "g/shop-was", "read": True, "build": [{"runtime": "node", "version": "20", "image": "node:20-slim", "jobs": ["build"]}],
            "code": {"node": "22", "node_from": ".nvmrc", "node_rule": "exact"}}
    client.post("/api/cicd/shape", json={"shapes": [_shape("shop was", versions=versions, repo=repo)]}, headers=AUTH)
    row = client.get("/api/cicd/shape").json()[0]
    assert row["versions"] == versions and row["repo"] == repo
