"""다시 수집 — 화면 버튼 요청 → 수집기가 가져가 처리(중앙은 수집하지 않음)."""
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import CollectRequest

AUTH = {"Authorization": "Bearer dev-runner-token"}


def test_button_request_claim_finish_flow(client):
    # 처음엔 요청·수집기 없음
    assert client.get("/api/collect/status").json() == {"request": None, "collector": None}
    # 화면 버튼(토큰 없이) → 요청됨, 연타하면 같은 요청
    r = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    assert r["status"] == "pending" and r["reused"] is False
    again = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    assert again["id"] == r["id"] and again["reused"] is True
    # 수집기만(러너 토큰) 가져갈 수 있음
    assert client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}).status_code == 401
    got = client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv", "mode": "gitlab"}, headers=AUTH).json()
    assert got["request"]["id"] == r["id"] and got["request"]["status"] == "running" and got["request"]["collector"] == "srv"
    # 수집 중엔 다시 가져갈 게 없음, 수집기는 켜짐으로 보임
    assert client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH).json() == {"request": None}
    st = client.get("/api/collect/status").json()
    assert st["request"]["status"] == "running" and st["collector"]["alive"] is True and st["collector"]["name"] == "srv"
    # 끝 → 완료 + 한 줄 요약, 작업이력에 남음
    done = client.post(f"/api/collect/requests/{r['id']}/finish", json={"ok": True, "message": "17개 서비스"}, headers=AUTH).json()
    assert done["status"] == "done" and done["message"] == "17개 서비스" and done["finished_at"]
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "collect.request" in actions and "collect.done" in actions
    # 끝난 뒤엔 버튼이 새 요청을 만듦
    assert client.post("/api/collect/requests", json={"kind": "shape"}).json()["reused"] is False


def test_failed_and_stale_running_and_unknown_kind(client):
    r = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH)
    fail = client.post(f"/api/collect/requests/{r['id']}/finish", json={"ok": False, "message": "GitLab 토큰 없음"}, headers=AUTH).json()
    assert fail["status"] == "failed" and fail["message"] == "GitLab 토큰 없음"
    # 수집 중으로 15분 넘게 → 수집기가 멈춘 것 → 다음 확인 때 실패로
    r2 = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH)
    with SessionLocal() as db:
        row = db.get(CollectRequest, r2["id"])
        row.started_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        db.commit()
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH)
    st = client.get("/api/collect/status").json()["request"]
    assert st["id"] == r2["id"] and st["status"] == "failed" and "멈춘" in st["message"]
    assert client.post("/api/collect/requests", json={"kind": "nope"}).status_code == 400
    assert client.post("/api/collect/requests/999/finish", json={"ok": True}, headers=AUTH).status_code == 404


def test_collector_seen_long_ago_is_not_alive(client):
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "pc"}, headers=AUTH)
    from app.models import Collector

    with SessionLocal() as db:
        c = db.query(Collector).filter(Collector.name == "pc").first()
        c.last_seen_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        db.commit()
    assert client.get("/api/collect/status").json()["collector"]["alive"] is False  # 화면: '수집기가 꺼져 있어요'
