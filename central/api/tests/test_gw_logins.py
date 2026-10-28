"""gw 접속 기록(2단계) — 그 인증서로 어느 gw 에 언제 들어갔나. 운영자만 본다.
'못 봤다' · '보고 안 하는 gw' 를 '아무도 안 들어왔다' 로 보이지 않는다."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from app.db import SessionLocal
from app.inventory_source import InventoryError
from app.models import AccessLogSnapshot
from app.routers import access_log
from tests.test_auth import _proxy, _proxy_jwt, _rsa_pair

AUTH = {"Authorization": "Bearer dev-runner-token"}
URL = "/api/access-log/gw-logins"


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _gw(name, **kw):
    base = {"gw": name, "host": f"{name}-host", "last_report_at": _ago(60), "every_seconds": 300, "read_ok": True,
            "why": None, "log_source": "journal", "files_read": 1, "lines_read": 40}
    return {**base, **kw}


LOGIN_NEW = {"at": "2026-10-28T05:21:38.619202Z", "gw": "gw-shop-dev", "account": "ubuntu", "kind": "person",
             "who": "ops@example.com", "serial": "776cb41cedacd9d8", "issued_at": "2026-10-28T05:04:58.434246Z",
             "env": "dev", "role": "dev-ubuntu"}
LOGIN_OLD = {"at": "2026-10-27T01:00:00.000000Z", "gw": "gw-shop-stg", "account": "dev1", "kind": "person",
             "who": "dev@example.com", "serial": "0a0b0c0d0e0f1011", "issued_at": None, "env": None, "role": None}
MISSING = {"source": "idp-gw", "read_ok": False, "read_error": "파일 없음"}


def _snap(**kw):
    base = {"source": "idp-gw", "reader": "test-collector", "read_ok": True, "written_at": _ago(20), "host": "idp-host",
            "interval_seconds": 60, "window_days": 14, "audit_ok": True, "audit_reason": None, "files_read": 3,
            "lines_read": 812, "source_bad_lines": 0, "header_events": 2, "event_lines": 2, "bad_lines": 0,
            "truncated": False, "reports": 9, "bad_gws": 0, "events": [LOGIN_OLD, LOGIN_NEW],
            "gws": [_gw("gw-shop-dev"), _gw("gw-shop-stg")]}
    return {**base, **kw}


def _inv(monkeypatch, inv):
    """금고 목록(서버 탭) — 실제 금고 대신. 예외를 주면 '못 읽음'."""
    def fake():
        if isinstance(inv, Exception):
            raise inv
        return inv
    monkeypatch.setattr(access_log, "fetch_inventory", fake)


INVENTORY = {
    "dev": {"shop": {"gw": {"host": "gw-dev.example.local", "port": 22}, "servers": {"web-1": "web-1.example.local"}}},
    "stg": {"shop": {"gw": {"host": "gw-stg.example.local", "port": 22}, "servers": {}}},
    "prod": {"pay": {"gw": {"host": "gw-prod.example.local", "port": 22}, "servers": {}},
             "nogw": {"servers": {"db-1": "db-1.example.local"}}},  # gw 없는 항목은 견주지 않음
}


@pytest.fixture()
def local(monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)


def _get(client, headers=None):
    return client.get(URL, headers=headers or {}).json()


def test_off_before_anything_and_upload_needs_runner_token(client, local):
    s = _get(client)
    assert s["state"] == "off" and s["events"] == [] and s["gws"] == [] and "gw 접속 기록을 올린 적이" in s["reasons"][0]
    assert client.post(URL, json=_snap()).status_code == 401
    assert client.post(URL, json=_snap(), headers=AUTH).json() == {"ok": True}


def test_gw_row_and_issuance_row_do_not_overwrite_each_other(client, local):
    # 같은 표의 다른 줄 — 서로의 주소로 올리면 거절(모양이 다른 내용으로 덮지 않게)
    assert client.post(URL, json=_snap(source="idp"), headers=AUTH).status_code == 422
    assert client.post("/api/access-log", json=_snap(), headers=AUTH).status_code == 422
    client.post(URL, json=_snap(), headers=AUTH)
    assert client.get("/api/access-log").json()["state"] == "off"  # gw 만 올렸으면 발급 기록은 여전히 연결 전


def test_ok_logins_newest_first_and_gw_report_states(client, local):
    gws = [_gw("gw-shop-dev"),
           _gw("gw-shop-stg", read_ok=False, why="journalctl 권한 없음"),
           _gw("gw-old-dev", last_report_at=_ago(16 * 60)),  # 5분 × 3 = 15분 넘음
           _gw("gw-edge-dev", last_report_at=_ago(14 * 60)),  # 아직 15분 안
           _gw("gw-odd-dev", last_report_at="어제쯤")]
    client.post(URL, json=_snap(gws=gws), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["reasons"] == [] and s["notes"] == []
    assert [e["gw"] for e in s["events"]] == ["gw-shop-dev", "gw-shop-stg"]  # 최신순
    assert s["events"][0]["serial"] == "776cb41cedacd9d8"
    by = {g["gw"]: g for g in s["gws"]}
    assert {k: by[k]["state"] for k in by} == {"gw-shop-dev": "ok", "gw-shop-stg": "unknown", "gw-old-dev": "stale",
                                               "gw-edge-dev": "ok", "gw-odd-dev": "unknown"}
    assert by["gw-shop-stg"]["reason"] == "못 봄 — gw 가 자기 접속 기록을 못 읽음: journalctl 권한 없음"
    assert by["gw-old-dev"]["reason"].startswith("보고 끊김 — 마지막 보고가 16분 전")
    assert by["gw-odd-dev"]["reason"] == "못 봄 — 마지막 보고 시각을 못 읽음"
    assert s["reporting"] == 2 and s["gws_known"] is True and s["reports"] == 9
    # 금고 목록이 꺼져 있으면(기본) '보고 안 함' 은 견줄 수 없음 — 모른다고 말함
    assert s["inventory"]["state"] == "off" and "보고 안 하는 gw 가 있는지 몰라요" in s["inventory"]["reason"]
    assert all(g["listed"] is None for g in s["gws"])


def test_gw_in_inventory_but_not_reporting_is_silent_not_no_logins(client, local, monkeypatch):
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(gws=[_gw("gw-shop-dev"), _gw("gw-lab-dev")]), headers=AUTH)
    s = _get(client)
    by = {g["gw"]: g for g in s["gws"]}
    assert set(by) == {"gw-shop-dev", "gw-lab-dev", "gw-shop-stg", "gw-pay-prod"}  # gw 없는 항목(nogw)은 빠짐
    assert by["gw-shop-stg"]["state"] == "silent" and by["gw-pay-prod"]["state"] == "silent"
    assert by["gw-pay-prod"]["reason"].startswith("보고 안 함 — 금고 목록에 있는 gw 인데 보고가 없어요")
    assert (by["gw-pay-prod"]["env"], by["gw-pay-prod"]["service"]) == ("prod", "pay")
    assert by["gw-shop-dev"]["listed"] is True and by["gw-lab-dev"]["listed"] is False  # 보고는 하는데 목록엔 없음
    assert s["inventory"] == {"state": "ok", "reason": None} and s["reporting"] == 2


def test_no_gw_reports_at_all_lists_every_inventory_gw_as_silent(client, local, monkeypatch):
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(gws=[], events=[], header_events=0, event_lines=0, reports=0), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["events"] == [] and s["reporting"] == 0
    assert [g["state"] for g in s["gws"]] == ["silent", "silent", "silent"]


def test_inventory_unreadable_says_comparison_unknown(client, local, monkeypatch):
    _inv(monkeypatch, InventoryError("금고 LIST inventory/metadata/dev: HTTP 403"))
    client.post(URL, json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["inventory"]["state"] == "error"
    assert s["inventory"]["reason"].startswith("금고 목록을 못 읽어 보고 안 하는 gw 가 있는지 몰라요")
    assert all(g["state"] != "silent" and g["listed"] is None for g in s["gws"])


def test_inventory_is_not_read_when_the_file_is_not_ok(client, local, monkeypatch):
    called = []
    monkeypatch.setattr(access_log, "fetch_inventory", lambda: called.append(1) or INVENTORY)
    client.post(URL, json=MISSING, headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["gws"] == [] and called == []
    assert s["inventory"]["state"] == "skipped"


def test_header_without_gws_means_per_gw_status_unknown(client, local, monkeypatch):
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(gws=None), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["gws_known"] is False and s["gws"] == []  # '보고 안 함' 으로도 안 그림
    assert "gw 마다 보고 상태가 파일에 없어요 — 보고 안 하는 gw 를 가릴 수 없어요" in s["notes"]


def test_notes_for_bad_gw_entries(client, local):
    client.post(URL, json=_snap(bad_gws=2, bad_lines=1, event_lines=3), headers=AUTH)
    assert _get(client)["notes"] == ["깨져서 뺀 줄 1개", "파일 머리에는 2건인데 3줄을 받았어요", "깨져서 뺀 gw 보고 칸 2개"]


@pytest.mark.parametrize(
    "snap, why",
    [
        (MISSING, "못 봄 — 요약 파일이 없어요"),  # IdP 반영 전 — 빈 표가 아니라 못 봄
        ({"audit_ok": False, "audit_reason": "감사 기록 없음"}, "못 봄 — IdP 가 금고 기록을 못 읽음: 감사 기록 없음"),
        ({"written_at": _ago(10 * 60)}, "멈춤 — 요약 기록이 10분째 그대로예요"),
        ({"files_read": 0}, "못 봄 — 금고 기록 파일을 하나도 못 읽었어요"),
        ({"lines_read": 0}, "못 봄 — 금고 기록이 비어 있어요"),
    ],
)
def test_unknown_hides_logins_and_gws(client, local, snap, why):
    client.post(URL, json=snap if snap.get("read_ok") is False else _snap(**snap), headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith(why) and s["events"] == [] and s["gws"] == []


def test_missing_file_after_a_good_read_drops_old_gws(client, local):
    client.post(URL, json=_snap(), headers=AUTH)
    client.post(URL, json=MISSING, headers=AUTH)
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).filter_by(source="idp-gw").one()
        assert (r.gws, r.reports, r.bad_gws, r.events) == (None, None, None, "[]")  # 지난 것을 지금 것처럼 남기지 않음
    assert _get(client)["state"] == "unknown"


def test_collector_silence_is_unknown(client, local):
    client.post(URL, json=_snap(), headers=AUTH)
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).filter_by(source="idp-gw").one()
        r.received_at = _ago(20 * 60)
        db.commit()
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"] == ["못 봄 — 수집기가 20분째 gw 접속 기록을 안 올림"] and s["gws"] == []


def test_stale_uses_file_interval_times_stale_factor(client, local, monkeypatch):
    client.post(URL, json=_snap(written_at=_ago(150), interval_seconds=30), headers=AUTH)
    assert _get(client)["state"] == "unknown"  # 30초 × 5배
    monkeypatch.setattr(settings, "ct_host_status_stale_factor", 10)
    assert _get(client)["state"] == "ok"


# ── 누가 보나 ──────────────────────────────────────────────

def test_none_mode_without_local_preview_is_no_identity(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    client.post(URL, json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "no_identity" and s["events"] == [] and s["gws"] == []
    assert "example.com" not in json.dumps(s, ensure_ascii=False)


def test_only_operators_see_it_in_proxy_mode(client, monkeypatch):
    client.post(URL, json=_snap(), headers=AUTH)
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)

    def as_(groups):
        return {"X-authentik-jwt": _proxy_jwt(priv, groups=groups)}

    assert _get(client, as_(["server-admin"]))["state"] == "ok"
    assert _get(client, as_(["developer", "server-admin"]))["state"] == "ok"
    r = client.get(URL, headers=as_(["viewer"]))
    assert r.status_code == 403 and r.json() == {"detail": "운영자만 볼 수 있어요"}
    r = client.get(URL, headers=as_(["developer"]))  # 개발자는 main.py 의 '서버 탭만' 이 먼저 막음
    assert r.status_code == 403 and r.json() == {"detail": "개발자는 서버 탭만 볼 수 있어요"}
    s = _get(client)  # 신분증 없음 = 누군지 모름
    assert s["state"] == "no_identity" and s["events"] == []
    assert client.post(URL, json=_snap(), headers=AUTH).status_code == 200  # 수집기는 proxy 모드에서도 올림


# ── 수집기가 실제로 읽고 올린 그대로(손으로 만든 몸통 없이) ─────────────

def _file(tmp_path, lines):
    f = tmp_path / "gw-logins.jsonl"
    f.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n")
    return str(f)


def _upload_from_file(client, path):
    from runner.accesslog import read_gw_logins
    from runner.api import CentralAPI

    api = CentralAPI("http://unused", "unused")
    client.headers.update(AUTH)
    api._client = client  # 수집기의 HTTP 를 그대로 앱으로 — 몸통 모양 · 이름 순서까지 실제와 같다
    api.upload_gw_logins("idp-gw", "test-collector", read_gw_logins(path))
    client.headers.pop("Authorization")


def test_collector_file_to_screen_end_to_end(client, local, tmp_path, monkeypatch):
    """IdP 가 쓰는 모양 그대로의 파일 → read_gw_logins → CentralAPI.upload_gw_logins → GET.
    파일 머리 · gws 칸에 source 가 있어도(openbao-audit · journal) 올리는 이름 'idp-gw' 를 덮지 않는다(#72 교훈)."""
    _inv(monkeypatch, INVENTORY)
    head = {"written_at": _ago(20), "host": "idp-host", "interval_seconds": 60, "window_days": 14, "source": "openbao-audit",
            "read_ok": True, "why": None, "files_read": 15, "lines_read": 2600, "bad_lines": 0, "reports": 4,
            "gws": [{"gw": "gw-shop-dev", "host": "shop-gw-1", "last_report_at": _ago(90).replace("+00:00", ".123456789Z"),
                     "every_seconds": 300, "read_ok": True, "why": None, "source": "journal", "files_read": 1, "lines_read": 77},
                    {"gw": "gw-shop-stg", "host": "shop-gw-2", "last_report_at": _ago(60), "every_seconds": 300,
                     "read_ok": False, "why": "auth.log 권한 없음", "source": "auth.log", "files_read": 0, "lines_read": 0},
                    "깨진 칸"],
            "events": 4, "truncated": False}  # 깨진 줄 1 포함 4줄
    ns = {**LOGIN_NEW, "at": "2026-10-28T05:21:38.619202123Z", "issued_at": "2026-10-28T05:04:58.434246277Z"}
    again = {**ns, "at": "2026-10-28T05:40:00.000000001Z"}  # 같은 인증서로 두 번째 접속
    _upload_from_file(client, _file(tmp_path, [head, again, ns, "{깨진 줄", LOGIN_OLD]))

    s = _get(client)
    assert s["state"] == "ok", s["reasons"]
    assert (s["files_read"], s["lines_read"], s["reports"]) == (15, 2600, 4)
    assert [e["at"] for e in s["events"]] == ["2026-10-28T05:40:00.000000Z", "2026-10-28T05:21:38.619202Z",
                                              "2026-10-27T01:00:00.000000Z"]
    assert [e["serial"] for e in s["events"][:2]] == ["776cb41cedacd9d8"] * 2  # 한 인증서로 여러 번
    assert s["events"][0]["issued_at"] == "2026-10-28T05:04:58.434246Z" and s["events"][2]["issued_at"] is None
    by = {g["gw"]: g for g in s["gws"]}
    assert {k: by[k]["state"] for k in by} == {"gw-shop-dev": "ok", "gw-shop-stg": "unknown", "gw-pay-prod": "silent"}
    assert s["notes"] == ["깨져서 뺀 줄 1개", "깨져서 뺀 gw 보고 칸 1개"]
    with SessionLocal() as db:  # 'idp-gw' 줄에 들어갔고, 파일의 source 로 새 줄이 생기지 않음
        assert [r.source for r in db.query(AccessLogSnapshot).all()] == ["idp-gw"]


def test_collector_missing_file_end_to_end_is_unknown_not_empty(client, local, tmp_path):
    """IdP 반영 전 — 파일이 아직 없다. 수집기는 건너뛰지 않고 '못 봄 + 이유' 를 올리고, 화면은 빈 표가 아니라 못 봄."""
    _upload_from_file(client, str(tmp_path / "gw-logins.jsonl"))
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith("못 봄 — 요약 파일이 없어요")
    assert s["events"] == [] and s["gws"] == []
