"""사람 이름표 — 수집기가 올리고, 서버 탭(/api/access) · 접속 기록 탭(/api/access-log)에 이름을 붙인다.
규칙: '이름을 못 봤다' 를 '운영자 없음' 으로 보이지 않는다. 키는 이메일(소문자)."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from app.config import settings
from tests.test_access_log import EV_NEW, EV_OLD
from tests.test_access_log import _snap as _access_snap
from tests.test_access_view import INV, _inv, _oidc

AUTH = {"Authorization": "Bearer dev-runner-token"}
OPS = {"email": "ops@example.com", "username": "ops", "name": "Ops Person", "groups": ["server-admin"], "active": True}
ADMIN = {"email": "root@example.com", "username": "akadmin", "name": None, "groups": ["server-admin"], "active": True}
GONE = {"email": "gone@example.com", "username": "gone", "name": "Left Company", "groups": ["server-admin"], "active": False}
DEV = {"email": "devtest@example.local", "username": "devtest", "name": "Dev Test", "groups": ["developer"], "active": True}
OTHER = {"email": "dev@example.com", "username": "dev2", "name": "Second Dev", "groups": ["developer"], "active": False}


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _snap(**kw):
    base = {"source": "idp", "reader": "test-collector", "read_ok": True, "written_at": _ago(20), "host": "idp-host",
            "interval_seconds": 300, "origin": "authentik", "list_ok": True, "list_reason": None,
            "groups": {"server-admin": 3, "developer": 2}, "header_people": 5, "person_lines": 5, "bad_lines": 0,
            "truncated": False, "people": [OPS, GONE, ADMIN, DEV, OTHER]}  # GONE 이 가운데 — 활성 먼저 정렬을 보려고
    return {**base, **kw}


def _up(client, **kw):
    assert client.post("/api/idp-people", json=_snap(**kw), headers=AUTH).json() == {"ok": True}


@pytest.fixture()
def admin(monkeypatch):
    _inv(monkeypatch)
    return _oidc(monkeypatch, ["server-admin"])


def _rows(client, h):
    r = client.get("/api/access", headers=h).json()
    assert r["state"] == "ok"
    return r, r["people"][0], {p["email"]: p for p in r["people"][1:]}


# ── 서버 탭 ──

def test_upload_needs_runner_token(client):
    assert client.post("/api/idp-people", json=_snap()).status_code == 401


def test_operator_row_lists_real_names_active_first_inactive_marked(client, admin):
    _up(client)
    r, ops, _ = _rows(client, admin)
    assert ops["role"] == "admin" and ops["email"] == "server-admin 그룹 전원"  # 줄 이름(화면 키)은 그대로 — 선도 하나
    assert ops["members"] == [
        {"name": "Ops Person", "email": "ops@example.com", "active": True},
        {"name": "akadmin", "email": "root@example.com", "active": True},  # 표시 이름이 없으면 아이디
        {"name": "Left Company", "email": "gone@example.com", "active": False},  # 비활성은 맨 뒤
    ]
    assert ops["names_note"] is None and r["names"] == {"state": "ok", "reasons": []}


def test_developer_row_gets_the_name_matched_by_lower_case_email(client, monkeypatch):
    inv = json.loads(json.dumps(INV))
    inv["dev"]["oci-idp"]["users"]["devtest"]["email"] = "DevTest@Example.LOCAL"  # 금고에 대문자가 섞여 있어도
    _inv(monkeypatch, inv)
    _up(client)
    _, _, devs = _rows(client, _oidc(monkeypatch, ["server-admin"]))
    d = devs["DevTest@Example.LOCAL"]
    assert (d["name"], d["active"]) == ("Dev Test", True)


def test_developer_not_in_the_people_file_shows_email_only(client, admin):
    _up(client, people=[OPS])
    _, _, devs = _rows(client, admin)
    assert (devs["devtest@example.local"]["name"], devs["devtest@example.local"]["active"]) == (None, None)


def test_developers_see_names_too_in_the_server_tab(client, monkeypatch):
    _inv(monkeypatch)
    _up(client)
    r, ops, devs = _rows(client, _oidc(monkeypatch, ["developer"]))
    assert [m["name"] for m in ops["members"]] == ["Ops Person", "akadmin", "Left Company"]
    assert devs["devtest@example.local"]["name"] == "Dev Test"


@pytest.mark.parametrize("kw,why", [
    ({"list_ok": False, "list_reason": "authentik api: 503", "groups": None, "header_people": 0, "person_lines": 0,
      "people": []}, "IdP 가 Authentik 을 못 읽음: authentik api: 503"),
    ({"read_ok": False, "read_error": "파일 없음"}, "이름표 파일이 없어요"),
    ({"read_ok": False, "read_error": "첫 줄(머리)이 깨짐"}, "이름표 파일을 못 읽음: 첫 줄(머리)이 깨짐"),
    ({"written_at": _ago(1800)}, "이름표가 30분째 그대로예요"),  # 300초 × 5 = 25분 넘음
    ({"written_at": "어제쯤"}, "기록 시각을 못 읽음"),
])
def test_unknown_keeps_the_group_line_never_no_operators(client, admin, kw, why):
    _up(client, **kw)
    r, ops, devs = _rows(client, admin)
    assert r["names"]["state"] == "unknown" and why in r["names"]["reasons"][0]
    assert ops["email"] == "server-admin 그룹 전원" and ops["members"] == []
    assert ops["names_note"] == "이름 모름(이름표를 못 읽음)"
    assert devs["devtest@example.local"]["name"] is None
    assert "운영자 없음" not in json.dumps(r, ensure_ascii=False)


def test_before_any_upload_is_off_and_still_the_group_line(client, admin):
    r, ops, _ = _rows(client, admin)
    assert r["names"]["state"] == "off" and ops["members"] == [] and ops["names_note"] == "이름 모름(이름표 연결 전)"


def test_stale_uses_the_file_interval_300s_times_the_stale_factor(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "ct_host_status_stale_factor", 5.0)
    _up(client, written_at=_ago(1200))  # 20분 전 — 60초 주기로 봤다면 멈춤, 300초 주기라 정상
    r, ops, _ = _rows(client, admin)
    assert r["names"]["state"] == "ok" and len(ops["members"]) == 3
    _up(client, written_at=_ago(1200), interval_seconds=None)  # 머리에 주기가 없어도 300초로 본다
    assert _rows(client, admin)[0]["names"]["state"] == "ok"
    _up(client, written_at=_ago(1600))  # 26분 — 25분 넘음
    assert _rows(client, admin)[0]["names"]["state"] == "unknown"


def test_collector_silence_is_unknown(client, admin, monkeypatch):
    from app.db import SessionLocal
    from app.models import IdpPeople

    _up(client)
    with SessionLocal() as db:
        db.query(IdpPeople).one().received_at = _ago(3600)
        db.commit()
    r, ops, _ = _rows(client, admin)
    assert r["names"]["state"] == "unknown" and "수집기가" in r["names"]["reasons"][0] and ops["members"] == []


def test_unreadable_upload_drops_the_old_names(client, admin):
    """IdP 규칙과 같게 — 못 읽은 뒤에 지난 이름을 지금 것처럼 남기지 않는다."""
    _up(client)
    _up(client, read_ok=False, read_error="권한 없음")
    from app.db import SessionLocal
    from app.models import IdpPeople

    with SessionLocal() as db:
        row = db.query(IdpPeople).one()
        assert row.people == "[]" and row.groups is None and row.written_at is None


def test_group_count_mismatch_is_a_note_not_a_failure(client, admin):
    _up(client, people=[OPS, DEV], header_people=5, person_lines=5, bad_lines=3)
    r, ops, _ = _rows(client, admin)
    assert r["names"]["state"] == "ok" and [m["email"] for m in ops["members"]] == ["ops@example.com"]
    assert ops["names_note"] == "이름표 머리에는 운영자 3명인데 1명만 읽었어요"


def test_ok_but_no_server_admin_lines_is_still_not_no_operators(client, admin):
    _up(client, people=[DEV], groups={"server-admin": 0, "developer": 1})
    _, ops, _ = _rows(client, admin)
    assert ops["email"] == "server-admin 그룹 전원" and ops["members"] == []
    assert ops["names_note"] == "이름 모름(이름표에서 server-admin 사람을 못 찾음)"


# ── 접속 기록 탭 ──

@pytest.fixture()
def local(monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)


def test_access_log_gets_a_lower_case_email_to_name_map(client, local):
    client.post("/api/access-log", json=_access_snap(), headers=AUTH)
    _up(client, people=[{**DEV, "email": "dev@example.com"}, GONE])
    s = client.get("/api/access-log").json()
    assert s["state"] == "ok"
    assert s["names"]["state"] == "ok"
    assert s["names"]["people"] == {"dev@example.com": {"name": "Dev Test", "active": True},
                                    "gone@example.com": {"name": "Left Company", "active": False}}
    # who 는 그대로(이메일) — 이름은 화면이 이 표에서 찾는다
    assert {e["who"] for e in s["events"]} == {EV_OLD["who"], EV_NEW["who"]}


def test_access_log_names_unknown_is_an_empty_map_not_an_error(client, local):
    client.post("/api/access-log", json=_access_snap(), headers=AUTH)
    _up(client, list_ok=False, list_reason="group missing", people=[], groups=None)
    s = client.get("/api/access-log").json()
    assert s["state"] == "ok" and len(s["events"]) == 2  # 기록은 그대로 — 이름만 없음
    assert s["names"]["state"] == "unknown" and s["names"]["people"] == {}


def test_access_log_without_identity_has_no_names(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    _up(client)
    s = client.get("/api/access-log").json()
    assert s["state"] == "no_identity" and "names" not in s and "Ops Person" not in json.dumps(s)


# ── 끝에서 끝까지 ──

def test_collector_file_to_both_tabs_end_to_end(client, local, monkeypatch, tmp_path):
    """수집기가 실제로 읽고(read_people) 실제로 올린(CentralAPI) 그대로 화면까지 — 중간을 손으로 만들지 않는다.
    파일 머리의 source('authentik')가 올리는 'idp' 를 덮으면(#72) 중앙이 늘 '연결 전' 이 된다 — 그것도 여기서 잡힌다."""
    from runner.api import CentralAPI
    from runner.people import read_people

    head = {"written_at": _ago(30), "host": "idp-host", "interval_seconds": 300, "source": "authentik", "read_ok": True,
            "why": None, "groups": {"server-admin": 3, "developer": 1}, "people": 4}
    f = tmp_path / "people.jsonl"
    lines = [head, {**DEV, "email": "devtest@example.local"}, GONE, OPS, {**ADMIN, "name": ""}]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    api = CentralAPI("http://unused", "unused")
    client.headers.update(AUTH)
    api._client = client  # 수집기의 HTTP 를 그대로 앱으로 — 몸통 모양 · 이름 순서까지 실제와 같다
    api.upload_people("idp", "test-collector", read_people(str(f)))
    api.upload_access_log("idp", "test-collector", {**_access_snap(), "source": "x"})
    client.headers.pop("Authorization")

    _inv(monkeypatch)
    r = client.get("/api/access").json()
    assert r["names"] == {"state": "ok", "reasons": []}
    ops = r["people"][0]
    assert [(m["name"], m["active"]) for m in ops["members"]] == [("Ops Person", True), ("akadmin", True), ("Left Company", False)]
    assert r["people"][1]["name"] == "Dev Test"

    s = client.get("/api/access-log").json()
    assert s["names"]["state"] == "ok" and s["names"]["people"]["devtest@example.local"]["name"] == "Dev Test"
