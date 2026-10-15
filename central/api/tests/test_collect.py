"""다시 수집 — 화면 버튼 요청 → 수집기가 가져가 처리(중앙은 수집하지 않음)."""
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Collector, CollectRequest

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _heartbeat(client, name="srv"):
    """수집기가 켜져 있다는 표시(요청이 없을 때의 claim)."""
    assert client.post("/api/collect/claim", json={"kind": "shape", "collector": name, "mode": "gitlab"}, headers=AUTH).json() == {"request": None}


def _ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_button_request_claim_finish_flow(client):
    # 처음엔 요청·수집기 없음 → 수집기가 꺼져 있으면 요청을 받지 않음(아무도 안 가져갈 요청을 쌓지 않음)
    assert client.get("/api/collect/status").json() == {"request": None, "collector": None}
    off = client.post("/api/collect/requests", json={"kind": "shape"})
    assert off.status_code == 409 and "수집기가 꺼져" in off.json()["detail"]
    _heartbeat(client)
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
    _heartbeat(client)
    st = client.get("/api/collect/status").json()
    assert st["request"]["status"] == "running" and st["collector"]["alive"] is True and st["collector"]["name"] == "srv"
    # 끝 → 완료 + 한 줄 요약, 작업이력에 남음
    done = client.post(f"/api/collect/requests/{r['id']}/finish", json={"ok": True, "message": "17개 서비스"}, headers=AUTH).json()
    assert done["status"] == "done" and done["message"] == "17개 서비스" and done["finished_at"]
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert "collect.request" in actions and "collect.done" in actions
    # 끝난 뒤엔 버튼이 새 요청을 만듦
    assert client.post("/api/collect/requests", json={"kind": "shape"}).json()["reused"] is False


def test_failed_stale_running_expired_pending_and_unknown_kind(client):
    _heartbeat(client)
    r = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH)
    fail = client.post(f"/api/collect/requests/{r['id']}/finish", json={"ok": False, "message": "GitLab 토큰 없음"}, headers=AUTH).json()
    assert fail["status"] == "failed" and fail["message"] == "GitLab 토큰 없음"
    # 수집 중으로 15분 넘게 → 수집기가 멈춘 것 → 다음 확인 때 실패로
    r2 = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    client.post("/api/collect/claim", json={"kind": "shape", "collector": "srv"}, headers=AUTH)
    with SessionLocal() as db:
        db.get(CollectRequest, r2["id"]).started_at = _ago(20)
        db.commit()
    st = client.get("/api/collect/status").json()["request"]  # 화면이 상태를 볼 때도 닫힘
    assert st["id"] == r2["id"] and st["status"] == "failed" and "멈춘" in st["message"]
    # 요청됨으로 10분 동안 아무도 안 가져감(수집기가 꺼져 있었음) → 취소 — 화면이 '요청됨'에 영원히 멈추지 않게
    r3 = client.post("/api/collect/requests", json={"kind": "shape"}).json()
    with SessionLocal() as db:
        db.get(CollectRequest, r3["id"]).requested_at = _ago(11)
        db.commit()
    st = client.get("/api/collect/status").json()["request"]
    assert st["id"] == r3["id"] and st["status"] == "failed" and "가져가지 않아 취소" in st["message"]
    assert client.post("/api/collect/requests", json={"kind": "nope"}).status_code == 400
    assert client.post("/api/collect/requests/999/finish", json={"ok": True}, headers=AUTH).status_code == 404


def test_collector_seen_long_ago_is_not_alive(client):
    _heartbeat(client, "pc")
    with SessionLocal() as db:
        db.query(Collector).filter(Collector.name == "pc").first().last_seen_at = _ago(5)
        db.commit()
    assert client.get("/api/collect/status").json()["collector"]["alive"] is False  # 화면: 버튼 꺼짐 + '수집기 꺼짐'
    assert client.post("/api/collect/requests", json={"kind": "shape"}).status_code == 409
