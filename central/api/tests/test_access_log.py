"""접속 기록(금고 인증서 발급 기록) — 수집기가 올리고, 운영자만 본다. '못 봤다' 를 '아무도 안 들어왔다' 로 보이지 않는다."""
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.db import SessionLocal
from app.models import AccessLogSnapshot
from tests.test_auth import _proxy, _proxy_jwt, _rsa_pair

AUTH = {"Authorization": "Bearer dev-runner-token"}
EV_OLD = {"at": "2026-10-27T09:00:00.000000Z", "kind": "person", "who": "dev@example.com", "env": "dev", "account": None,
          "role": "dev-gw", "serial": None, "result": "issued", "reason": None}
EV_NEW = {"at": "2026-10-28T01:20:03.123456Z", "kind": "person", "who": "dev@example.com", "env": "prod", "account": "ubuntu",
          "role": "prod-ubuntu", "serial": "11d1bda82b498807", "result": "denied", "reason": "permission denied"}
MISSING = {"source": "idp", "read_ok": False, "read_error": "파일 없음"}


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _snap(**kw):
    base = {"source": "idp", "reader": "test-collector", "read_ok": True, "written_at": _ago(20), "host": "idp-host",
            "interval_seconds": 60, "window_days": 14, "audit_ok": True, "audit_reason": None, "files_read": 3,
            "lines_read": 812, "source_bad_lines": 0, "header_events": 2, "event_lines": 2, "bad_lines": 0,
            "truncated": False, "events": [EV_OLD, EV_NEW]}
    return {**base, **kw}


@pytest.fixture()
def local(monkeypatch):
    """none 모드 + 로컬 미리보기 — 판정 시험용(누가 보나는 따로 시험)."""
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)


def _get(client, headers=None):
    return client.get("/api/access-log", headers=headers or {}).json()


def test_off_before_anything_and_upload_needs_runner_token(client, local):
    s = _get(client)
    assert s["state"] == "off" and s["events"] == [] and "연결 전" in s["reasons"][0]
    assert client.post("/api/access-log", json=_snap()).status_code == 401  # 화면(토큰 없음)은 못 올림
    assert client.post("/api/access-log", json=_snap(), headers=AUTH).json() == {"ok": True}


def test_ok_shows_events_newest_first_with_header(client, local):
    client.post("/api/access-log", json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["reasons"] == [] and s["notes"] == []
    assert [e["env"] for e in s["events"]] == ["prod", "dev"]  # 최신순
    assert (s["window_days"], s["files_read"], s["lines_read"], s["host"]) == (14, 3, 812, "idp-host")
    assert 0 <= s["written_age_seconds"] < 60 and s["stale_after_seconds"] == 300  # 60초 × 5배(서버 상태 한 줄과 같은 배수)


def test_notes_for_truncated_bad_lines_and_count_mismatch_but_still_ok(client, local):
    client.post("/api/access-log", json=_snap(truncated=True, header_events=5000, source_bad_lines=3, bad_lines=1, event_lines=4999),
                headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok"
    assert s["notes"] == ["최근 5000건까지만 받았어요", "IdP 가 금고 기록에서 못 읽은 줄 3개", "깨져서 뺀 줄 1개",
                          "파일 머리에는 5000건인데 4999줄을 받았어요"]


def test_no_events_is_ok_only_when_audit_was_actually_read(client, local):
    # 읽은 금고 기록이 있고(>0) 발급이 0건이면 '최근 N일 접속 없음' 이 맞다
    client.post("/api/access-log", json=_snap(events=[], header_events=0, event_lines=0), headers=AUTH)
    s = _get(client)
    assert (s["state"], s["events"], s["lines_read"]) == ("ok", [], 812)
    # 칸이 없으면(예전 모양) read_ok 만으로 판단
    client.post("/api/access-log", json=_snap(events=[], lines_read=None, files_read=None), headers=AUTH)
    assert _get(client)["state"] == "ok"


@pytest.mark.parametrize(
    "snap, why",
    [
        (MISSING, "못 봄 — 요약 파일이 없어요"),  # IdP 반영 전 — 빈 표가 아니라 못 봄
        ({"source": "idp", "read_ok": False, "read_error": "첫 줄(머리)이 깨짐"}, "못 봄 — 요약 파일을 못 읽음: 첫 줄(머리)이 깨짐"),
        ({"audit_ok": False, "audit_reason": "감사 기록이 비어 있다", "events": []}, "못 봄 — IdP 가 금고 기록을 못 읽음: 감사 기록이 비어 있다"),
        ({"audit_ok": None}, "못 봄 — IdP 가 금고 기록을 못 읽음: 이유 모름"),
        ({"written_at": _ago(10 * 60)}, "멈춤 — 요약 기록이 10분째 그대로예요"),
        ({"written_at": "어제쯤"}, "못 봄 — 기록 시각을 못 읽음"),
        ({"files_read": 0, "events": []}, "못 봄 — 금고 기록 파일을 하나도 못 읽었어요"),
        ({"lines_read": 0, "events": []}, "못 봄 — 금고 기록이 비어 있어요"),
        ({"lines_read": 0}, "못 봄 — 금고 기록이 비어 있어요"),  # 0줄인데 이벤트가 있으면(있을 수 없는 모양) 믿지 않음
    ],
)
def test_unknown_hides_events_and_says_why(client, local, snap, why):
    client.post("/api/access-log", json=snap if snap.get("read_ok") is False else _snap(**snap), headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith(why) and s["events"] == []


def test_stale_uses_the_file_interval_times_the_stale_factor(client, local, monkeypatch):
    client.post("/api/access-log", json=_snap(written_at=_ago(150), interval_seconds=30), headers=AUTH)
    assert _get(client)["state"] == "unknown"  # 30초 × 5배 = 150초 넘음
    monkeypatch.setattr(settings, "ct_host_status_stale_factor", 10)
    assert _get(client)["state"] == "ok"


def test_missing_file_after_a_good_read_is_still_unknown(client, local):
    client.post("/api/access-log", json=_snap(), headers=AUTH)
    client.post("/api/access-log", json=MISSING, headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["events"] == [] and s["written_at"] is None  # 지난 기록을 지금 것처럼 남기지 않음


def test_collector_silence_is_unknown(client, local):
    client.post("/api/access-log", json=_snap(), headers=AUTH)
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).one()
        r.received_at = _ago(20 * 60)
        db.commit()
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"] == ["못 봄 — 수집기가 20분째 접속 기록을 안 올림"] and s["events"] == []


def test_each_upload_replaces_the_snapshot(client, local):
    client.post("/api/access-log", json=_snap(), headers=AUTH)
    client.post("/api/access-log", json=_snap(events=[EV_OLD], lines_read=5), headers=AUTH)
    s = _get(client)
    assert [e["env"] for e in s["events"]] == ["dev"] and s["lines_read"] == 5
    with SessionLocal() as db:
        assert db.query(AccessLogSnapshot).count() == 1


# ── 누가 보나 ──────────────────────────────────────────────

def test_none_mode_without_local_preview_is_no_identity_even_with_data(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    client.post("/api/access-log", json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "no_identity" and s["events"] == []
    assert "dev@example.com" not in str(s)


def test_only_operators_see_it_in_proxy_mode(client, monkeypatch):
    client.post("/api/access-log", json=_snap(), headers=AUTH)  # 수집기(러너 토큰)는 proxy 와 상관없이 올림
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)

    def as_(groups):
        return {"X-authentik-jwt": _proxy_jwt(priv, groups=groups)}

    assert _get(client, as_(["server-admin"]))["state"] == "ok"
    assert _get(client, as_(["developer", "server-admin"]))["state"] == "ok"
    r = client.get("/api/access-log", headers=as_(["viewer"]))
    assert r.status_code == 403 and r.json() == {"detail": "운영자만 볼 수 있어요"}
    r = client.get("/api/access-log", headers=as_(["developer"]))  # 개발자는 main.py 의 '서버 탭만' 이 먼저 막음
    assert r.status_code == 403 and r.json() == {"detail": "개발자는 서버 탭만 볼 수 있어요"}
    s = _get(client)  # 신분증 없음 = 누군지 모름
    assert s["state"] == "no_identity" and s["events"] == []
    # 수집기의 올리기는 proxy 모드에서도 그대로 닿는다
    assert client.post("/api/access-log", json=_snap(), headers=AUTH).status_code == 200


def test_collector_file_to_screen_end_to_end(client, local, tmp_path):
    """수집기가 실제로 읽고(read_access) 실제로 올린(CentralAPI) 그대로 화면까지 — 중간을 손으로 만들지 않는다.
    10-28 운영: 파일 머리의 source('openbao-audit')가 올릴 때 'idp' 를 덮어 중앙이 늘 '연결 전' 이었는데,
    위 시험들은 API 에 source='idp' 를 직접 넣어서 못 잡았다."""
    import json

    from runner.accesslog import read_access
    from runner.api import CentralAPI

    head = {"written_at": _ago(20), "host": "idp-host", "interval_seconds": 60, "window_days": 14, "source": "openbao-audit",
            "read_ok": True, "why": None, "files_read": 15, "lines_read": 2600, "bad_lines": 0, "events": 2, "truncated": False}
    ev_ns = {**EV_NEW, "at": "2026-10-28T03:04:06.322348939Z"}  # 실제 파일처럼 나노초
    f = tmp_path / "access.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in (head, ev_ns, EV_OLD)) + "\n")

    api = CentralAPI("http://unused", "unused")
    client.headers.update(AUTH)
    api._client = client  # 수집기의 HTTP 를 그대로 앱으로 — 몸통 모양 · 이름 순서까지 실제와 같다
    api.upload_access_log("idp", "test-collector", read_access(str(f)))

    s = _get(client)
    assert s["state"] == "ok", s["reasons"]
    assert (s["files_read"], s["lines_read"], len(s["events"])) == (15, 2600, 2)
    assert s["events"][0]["at"].startswith("2026-10-28T03:04:06.322348")
