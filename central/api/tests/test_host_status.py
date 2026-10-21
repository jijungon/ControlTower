"""서버 상태(서버가 스스로 적는 status.json) — 수집기가 올리고, 화면은 정상 · 경보 · 모름 세 가지로.

규칙 하나: '못 봤다' 를 '정상' 으로 적지 않는다(못 읽음 · 낡음 · 수집기 멈춤 · ok 와 내용이 어긋남).
"""
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import SessionLocal
from app.models import HostStatus

AUTH = {"Authorization": "Bearer dev-runner-token"}


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _snap(**kw):
    base = {"source": "idp", "reader": "test-collector", "read_ok": True, "written_at": _ago(10), "host": "test-host",
            "interval_seconds": 60, "ok": True, "problems": [], "unread": [], "signals": {"disk": []}}
    return {**base, **kw}


def _state(client):
    rows = client.get("/api/host-status").json()
    assert len(rows) == 1
    return rows[0]


def test_feature_off_shows_nothing_and_upload_needs_runner_token(client):
    assert client.get("/api/host-status").json() == []  # 아무도 안 올림 = 기능 꺼짐 → 화면에 아무것도
    assert client.post("/api/host-status", json=_snap()).status_code == 401  # 화면(토큰 없음)은 못 올림
    assert client.post("/api/host-status", json=_snap(), headers=AUTH).json() == {"ok": True}


def test_ok_only_when_ok_and_nothing_found_and_nothing_unread(client):
    client.post("/api/host-status", json=_snap(), headers=AUTH)
    s = _state(client)
    assert (s["state"], s["reasons"], s["host"]) == ("ok", [], "test-host")
    assert 0 <= s["written_age_seconds"] < 60 and s["stale_after_seconds"] == 300  # 60초 × 5배


def test_alert_shows_both_problems_and_unread(client):
    """① ok=false 면 경보 — problems 만 보여 주면 unread 가 '검사했는데 문제 없음' 처럼 보인다(거짓)."""
    client.post("/api/host-status", json=_snap(ok=False, problems=["systemd 실패: a.service"], unread=["breakglass: 계정이 없다"]), headers=AUTH)
    s = _state(client)
    assert s["state"] == "alert"
    assert s["problems"] == ["systemd 실패: a.service"] and s["unread"] == ["breakglass: 계정이 없다"]


def test_ok_true_is_not_trusted_when_something_is_unread_or_reasons_empty(client):
    client.post("/api/host-status", json=_snap(ok=True, unread=["disk: df 실패"]), headers=AUTH)
    assert _state(client)["state"] == "alert"  # ok 가 참이어도 못 본 것이 있으면 정상 아님
    client.post("/api/host-status", json=_snap(ok=False, problems=[], unread=[]), headers=AUTH)
    s = _state(client)
    assert s["state"] == "alert" and s["reasons"] == ["ok=false 인데 이유가 비어 있음"]


def test_stale_file_is_an_alert_not_green(client):
    """② 파일이 있다고 정상이 아님 — 적는 쪽 타이머가 죽으면 파일은 낡은 채 남는다."""
    client.post("/api/host-status", json=_snap(written_at=_ago(301)), headers=AUTH)  # 60초 × 5배 = 300초 넘김
    s = _state(client)
    assert s["state"] == "alert" and s["reasons"] == ["상태 기록이 5분째 멈춤 — 적는 쪽 타이머 확인"]
    client.post("/api/host-status", json=_snap(written_at=_ago(299)), headers=AUTH)
    assert _state(client)["state"] == "ok"


def test_stale_factor_is_a_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_host_status_stale_factor", 2.0)
    client.post("/api/host-status", json=_snap(written_at=_ago(121)), headers=AUTH)  # 60초 × 2배
    assert _state(client)["state"] == "alert"


def test_unreadable_file_is_unknown_and_keeps_last_good_record(client):
    """③ 파일을 못 읽는 것(없음 · JSON 깨짐 · 권한)은 '정상' 이 아니라 '모름'."""
    client.post("/api/host-status", json=_snap(), headers=AUTH)
    client.post("/api/host-status", json={"source": "idp", "reader": "test-collector", "read_ok": False, "read_error": "파일 없음"}, headers=AUTH)
    s = _state(client)
    assert s["state"] == "unknown" and s["reasons"] == ["상태 파일을 못 읽음 — 파일 없음"]
    assert s["host"] == "test-host" and s["written_at"]  # 마지막으로 읽은 기록은 남김


def test_short_interval_stale_is_alert_not_collector_silence(client):
    """파일 주기가 짧아도(6초) 수집기는 1분마다 다시 올림 — 기록이 멈춘 것을 '수집기 멈춤(모름)' 으로 잘못 보지 않게(실제로 겪음)."""
    client.post("/api/host-status", json=_snap(interval_seconds=6, written_at=_ago(75)), headers=AUTH)
    with SessionLocal() as db:  # 수집기는 70초 전에 마지막으로 올림 — 1분 주기 다시 올리기 사이
        db.query(HostStatus).update({"received_at": _ago(70)})
        db.commit()
    s = _state(client)
    assert s["state"] == "alert" and s["reasons"] == ["상태 기록이 1분째 멈춤 — 적는 쪽 타이머 확인"]
    client.post("/api/host-status", json=_snap(interval_seconds=6, written_at=_ago(40)), headers=AUTH)
    assert _state(client)["reasons"] == ["상태 기록이 40초째 멈춤 — 적는 쪽 타이머 확인"]  # '0분째' 가 아니라 초로


def test_collector_silence_and_bad_timestamp_are_unknown(client):
    client.post("/api/host-status", json=_snap(), headers=AUTH)
    with SessionLocal() as db:  # 수집기가 6분 전에 마지막으로 올림(죽었거나 멈춤)
        db.query(HostStatus).update({"received_at": _ago(360)})
        db.commit()
    s = _state(client)
    assert s["state"] == "unknown" and s["reasons"] == ["수집기가 6분째 상태를 안 올림"]
    client.post("/api/host-status", json=_snap(written_at="어제 아침"), headers=AUTH)
    s = _state(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith("기록 시각을 못 읽음")
