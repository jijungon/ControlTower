"""서버 접속 기록(3단계) — 그 인증서로 gw 뒤 어느 서버에 언제 들어갔나. 운영자만 본다.
'못 봤다' · '안 읽는 서버' 를 '아무도 안 들어왔다' 로 보이지 않는다."""
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
URL = "/api/access-log/server-logins"


def _ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _srv(server, gw="gw-a", env="dev", service="svc-a", **kw):
    """gw · 서버 한 곳의 마지막 읽기. 목록과 잇는 건 (env, service, server) 뿐(없으면 못 이음)."""
    base = {"server": server, "gw": gw, "env": env, "service": service, "host": f"{server}-host", "last_read_at": _ago(60),
            "read_ok": True, "why": None, "log_source": "files", "files_read": 3, "lines_read": 1200}
    return {**base, **kw}


LOGIN_NEW = {"at": "2026-10-28T23:59:01.652873Z", "server": "srv-a", "gw": "gw-a", "service": "svc-a", "account": "ubuntu",
             "kind": "person", "who": "person@example.com", "serial": "3560879729764d4",
             "issued_at": "2026-10-28T23:58:56.834689Z", "env": "dev", "role": "dev-ubuntu"}
LOGIN_OLD = {"at": "2026-10-28T10:00:00.000000Z", "server": "srv-b", "gw": "gw-a", "service": "svc-a", "account": "ubuntu",
             "kind": "person", "who": "person@example.com", "serial": "0a0b0c0d0e0f1011", "issued_at": None, "env": None, "role": None}
MISSING = {"source": "idp-server", "read_ok": False, "read_error": "파일 없음"}


def _snap(**kw):
    base = {"source": "idp-server", "reader": "test-collector", "read_ok": True, "written_at": _ago(20), "host": "idp-host",
            "interval_seconds": 60, "window_days": 14, "audit_ok": True, "audit_reason": None, "files_read": 3,
            "lines_read": 812, "source_bad_lines": 0, "header_events": 2, "event_lines": 2, "bad_lines": 0,
            "truncated": False, "reports": 173, "bad_servers": 0, "events": [LOGIN_OLD, LOGIN_NEW],
            "servers": [_srv("srv-a"), _srv("srv-b")]}
    return {**base, **kw}


def _inv(monkeypatch, inv):
    """금고 목록(서버 탭) — 실제 금고 대신. 예외를 주면 '못 읽음'."""
    def fake():
        if isinstance(inv, Exception):
            raise inv
        return inv
    monkeypatch.setattr(access_log, "fetch_inventory", fake)


INVENTORY = {
    "dev": {"svc-a": {"gw": {"host": "gw-a.example.local", "port": 22},
                      "servers": {"srv-a": "srv-a.example.local", "srv-b": "srv-b.example.local", "srv-new": "srv-new.example.local"}}},
    "stg": {"svc-a": {"gw": {"host": "gw-s.example.local", "port": 22}, "servers": {"srv-s": "srv-s.example.local"}}},
    "prod": {"nogw": {"servers": {"db-1": "db-1.example.local"}},  # gw 없는 항목 — 읽을 gw 가 없어 견주지 않음
             "pay": {"gw": {"host": "gw-p.example.local", "port": 22}}},  # 서버가 없는 항목
}


@pytest.fixture()
def local(monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)


def _get(client, headers=None):
    return client.get(URL, headers=headers or {}).json()


def _key(s):
    return f"{s['gw'] or '-'}:{s['server']}"  # 목록에만 있는 줄은 gw 가 없음(읽은 gw 가 없으니)


def test_off_before_anything_and_upload_needs_runner_token(client, local):
    s = _get(client)
    assert s["state"] == "off" and s["events"] == [] and s["servers"] == [] and "서버 접속 기록을 올린 적이" in s["reasons"][0]
    assert client.post(URL, json=_snap()).status_code == 401
    assert client.post(URL, json=_snap(), headers=AUTH).json() == {"ok": True}


def test_server_row_does_not_overwrite_issuance_or_gw_rows(client, local):
    # 같은 표의 다른 줄 — 서로의 주소로 올리면 거절(모양이 다른 내용으로 덮지 않게)
    assert client.post(URL, json=_snap(source="idp"), headers=AUTH).status_code == 422
    assert client.post(URL, json=_snap(source="idp-gw"), headers=AUTH).status_code == 422
    assert client.post("/api/access-log", json=_snap(), headers=AUTH).status_code == 422
    assert client.post("/api/access-log/gw-logins", json=_snap(), headers=AUTH).status_code == 422
    client.post(URL, json=_snap(), headers=AUTH)
    assert _get(client)["state"] == "ok"
    assert client.get("/api/access-log").json()["state"] == "off"  # 서버만 올렸으면 발급 · gw 기록은 여전히 연결 전
    assert client.get("/api/access-log/gw-logins").json()["state"] == "off"


def test_ok_logins_newest_first_and_server_read_states(client, local):
    srvs = [_srv("srv-a"),
            _srv("srv-b", read_ok=False, why="닿지 않는다 (시간 초과)"),
            _srv("srv-c", read_ok=False, why="도장을 안 받아 준다 — 그 서버가 금고 도장을 믿나", last_read_at=_ago(30 * 60)),
            _srv("srv-old", last_read_at=_ago(11 * 60)),   # 10분 넘음
            _srv("srv-edge", last_read_at=_ago(9 * 60)),   # 아직 10분 안
            _srv("srv-odd", last_read_at="어제쯤"),
            _srv("srv-nook", read_ok=None)]
    client.post(URL, json=_snap(servers=srvs), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["reasons"] == [] and s["notes"] == []
    assert [e["server"] for e in s["events"]] == ["srv-a", "srv-b"]  # 최신순
    assert s["events"][0]["serial"] == "3560879729764d4" and s["events"][1]["issued_at"] is None
    by = {x["server"]: x for x in s["servers"]}
    assert {k: by[k]["state"] for k in by} == {"srv-a": "ok", "srv-b": "failed", "srv-c": "failed", "srv-old": "stale",
                                               "srv-edge": "ok", "srv-odd": "unknown", "srv-nook": "unknown"}
    assert by["srv-b"]["reason"] == "그 서버 기록 못 읽음 — 닿지 않는다 (시간 초과)"  # 까닭을 고치지 않고 그대로
    assert by["srv-c"]["reason"] == "그 서버 기록 못 읽음 — 도장을 안 받아 준다 — 그 서버가 금고 도장을 믿나 · 마지막 시도도 30분 전(끊김)"
    assert by["srv-old"]["reason"].startswith("끊김 — 마지막으로 읽은 게 11분 전")
    assert by["srv-odd"]["reason"] == "모름 — 마지막으로 읽은 시각을 못 읽음"
    assert by["srv-nook"]["reason"] == "모름 — 그 서버 기록을 읽었는지 안 적혀 있어요"
    assert (by["srv-a"]["gw"], by["srv-a"]["env"], by["srv-a"]["service"]) == ("gw-a", "dev", "svc-a")
    assert s["reading"] == 2 and s["servers_known"] is True and s["reports"] == 173
    # 금고 목록이 꺼져 있으면(기본) '안 읽음' 은 견줄 수 없음 — 모른다고 말함
    assert s["inventory"]["state"] == "off" and "안 읽는 서버가 있는지 몰라요" in s["inventory"]["reason"]
    assert all(x["link"] == "unknown" for x in s["servers"]) and len(s["servers"]) == 7  # 목록을 모르면 '안 읽음' 줄을 더하지 않음


def test_inventory_server_without_a_read_is_not_read_not_no_logins(client, local, monkeypatch):
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(servers=[_srv("srv-a"), _srv("srv-b", read_ok=False, why="권한 없음"), _srv("srv-lab", service="lab")]),
                headers=AUTH)
    s = _get(client)
    by = {_key(x): x for x in s["servers"]}
    assert set(by) == {"gw-a:srv-a", "gw-a:srv-b", "gw-a:srv-lab", "-:srv-new", "-:srv-s"}  # gw 없는 항목(db-1)은 빠짐
    assert by["-:srv-new"]["state"] == "silent" and by["-:srv-s"]["state"] == "silent"
    assert by["-:srv-new"]["reason"].startswith("안 읽음 — 금고 목록에 있는 서버인데 그 gw 가 읽지 않아요")
    assert (by["-:srv-new"]["env"], by["-:srv-new"]["service"], by["-:srv-new"]["link"]) == ("dev", "svc-a", "listed")
    assert by["gw-a:srv-a"]["link"] == "listed" and by["gw-a:srv-b"]["link"] == "listed"  # 못 읽어도 목록엔 있음 — '안 읽음' 줄은 안 더함
    assert by["gw-a:srv-lab"]["link"] == "not_listed"  # 읽긴 하는데 그 키가 목록엔 없음
    assert s["inventory"] == {"state": "ok", "reason": None} and s["reading"] == 2 and s["unlinked"] == 0
    # 읽은 것 먼저(gw → 환경/서비스 → 서버), 목록에만 있는 줄은 뒤
    assert [_key(x) for x in s["servers"]] == ["gw-a:srv-lab", "gw-a:srv-a", "gw-a:srv-b", "-:srv-new", "-:srv-s"]


def test_link_is_by_env_service_server_never_by_name_alone(client, local, monkeypatch):
    """서버 이름이 목록 키와 같아도 env · service 가 없으면 못 이음 — 다른 환경 · 서비스의 같은 이름과도 잇지 않음."""
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(servers=[_srv("srv-a", env=None, service=None),  # 이름은 dev/svc-a/srv-a 같지만 env · service 없음
                                         _srv("srv-s", env="dev", service="svc-a")]), headers=AUTH)  # srv-s 는 stg 에만 있음
    s = _get(client)
    by = {_key(x): x for x in s["servers"]}
    assert by["gw-a:srv-a"]["link"] == "unlinked" and by["gw-a:srv-s"]["link"] == "not_listed"
    # 목록 쪽은 하나도 이어지지 않았고, 못 잇는 읽기가 있으니 단정하지 않음
    assert {k: by[k]["state"] for k in by if k.startswith("-:")} == {
        "-:srv-a": "maybe_silent", "-:srv-b": "maybe_silent", "-:srv-new": "maybe_silent", "-:srv-s": "maybe_silent"}
    assert by["-:srv-s"]["reason"] == "안 읽음일 수 있음 — 목록과 못 잇는 읽기 1개" and s["unlinked"] == 1


def test_no_server_reads_at_all_lists_every_inventory_server_as_not_read(client, local, monkeypatch):
    # 아무 gw 도 서버 읽기를 켜기 전(servers 가 빈 목록) — 목록의 서버는 모두 '안 읽음'
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(servers=[], events=[], header_events=0, event_lines=0, reports=0), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["events"] == [] and s["reading"] == 0 and s["unlinked"] == 0
    assert [(x["server"], x["state"]) for x in s["servers"]] == [
        ("srv-a", "silent"), ("srv-b", "silent"), ("srv-new", "silent"), ("srv-s", "silent")]


def test_inventory_unreadable_says_comparison_unknown(client, local, monkeypatch):
    _inv(monkeypatch, InventoryError("금고 LIST inventory/metadata/dev: HTTP 403"))
    client.post(URL, json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and s["inventory"]["state"] == "error" and len(s["servers"]) == 2
    assert s["inventory"]["reason"].startswith("금고 목록을 못 읽어 안 읽는 서버가 있는지 몰라요")
    assert all(x["state"] not in ("silent", "maybe_silent") and x["link"] == "unknown" for x in s["servers"])


def test_inventory_is_not_read_when_the_file_is_not_ok(client, local, monkeypatch):
    called = []
    monkeypatch.setattr(access_log, "fetch_inventory", lambda: called.append(1) or INVENTORY)
    client.post(URL, json=MISSING, headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["servers"] == [] and called == []
    assert s["inventory"]["state"] == "skipped"


def test_header_without_servers_means_per_server_status_unknown(client, local, monkeypatch):
    _inv(monkeypatch, INVENTORY)
    client.post(URL, json=_snap(servers=None), headers=AUTH)
    s = _get(client)
    assert s["state"] == "ok" and len(s["events"]) == 2  # 접속 줄은 읽었다
    assert s["servers_known"] is False and s["servers"] == []  # '안 읽음' 으로도 안 그림
    assert "서버마다 읽기 상태가 파일에 없어요 — 안 읽는 서버를 가릴 수 없어요" in s["notes"]


def test_notes_for_bad_server_entries(client, local):
    client.post(URL, json=_snap(bad_servers=2, bad_lines=1, event_lines=3), headers=AUTH)
    assert _get(client)["notes"] == ["깨져서 뺀 줄 1개", "파일 머리에는 2건인데 3줄을 받았어요", "깨져서 뺀 서버 읽기 칸 2개"]


@pytest.mark.parametrize(
    "snap, why",
    [
        (MISSING, "못 봄 — 요약 파일이 없어요"),
        ({"audit_ok": False, "audit_reason": "감사 기록 없음"}, "못 봄 — IdP 가 금고 기록을 못 읽음: 감사 기록 없음"),
        ({"written_at": _ago(10 * 60)}, "멈춤 — 요약 기록이 10분째 그대로예요"),
        ({"files_read": 0}, "못 봄 — 금고 기록 파일을 하나도 못 읽었어요"),
        ({"lines_read": 0}, "못 봄 — 금고 기록이 비어 있어요"),
    ],
)
def test_unknown_hides_logins_and_servers(client, local, snap, why):
    client.post(URL, json=snap if snap.get("read_ok") is False else _snap(**snap), headers=AUTH)
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith(why) and s["events"] == [] and s["servers"] == []


def test_missing_file_after_a_good_read_drops_old_servers(client, local):
    client.post(URL, json=_snap(), headers=AUTH)
    with SessionLocal() as db:
        assert len(json.loads(db.query(AccessLogSnapshot).filter_by(source="idp-server").one().servers)) == 2  # 먼저 실제로 들어감
    # 못 읽었다는 몸통에 칸이 딸려 와도(옛 수집기 등) 지난 것을 지금 것처럼 남기지 않음
    client.post(URL, json={**MISSING, "servers": [_srv("srv-a")], "reports": 5, "bad_servers": 1, "events": [LOGIN_NEW]}, headers=AUTH)
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).filter_by(source="idp-server").one()
        assert (r.servers, r.reports, r.bad_servers, r.events) == (None, None, None, "[]")
    assert _get(client)["state"] == "unknown"


def test_collector_silence_is_unknown(client, local):
    client.post(URL, json=_snap(), headers=AUTH)
    assert _get(client)["state"] == "ok"
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).filter_by(source="idp-server").one()
        r.received_at = _ago(20 * 60)
        db.commit()
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"] == ["못 봄 — 수집기가 20분째 서버 접속 기록을 안 올림"] and s["servers"] == []


# ── 누가 보나 ──────────────────────────────────────────────

def test_none_mode_without_local_preview_is_no_identity(client, monkeypatch):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    client.post(URL, json=_snap(), headers=AUTH)
    s = _get(client)
    assert s["state"] == "no_identity" and s["events"] == [] and s["servers"] == []
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

def _file(tmp_path, lines, name="server-logins.jsonl"):
    f = tmp_path / name
    f.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n")
    return str(f)


def _upload_from_file(client, path):
    from runner.accesslog import read_server_logins
    from runner.api import CentralAPI

    api = CentralAPI("http://unused", "unused")
    client.headers.update(AUTH)
    api._client = client  # 수집기의 HTTP 를 그대로 앱으로 — 몸통 모양 · 이름 순서까지 실제와 같다
    api.upload_server_logins("idp-server", "test-collector", read_server_logins(path))
    client.headers.pop("Authorization")


def test_collector_file_to_screen_end_to_end(client, local, tmp_path, monkeypatch):
    """IdP 가 쓰는 모양 그대로의 파일 → read_server_logins → CentralAPI.upload_server_logins → GET.
    파일 머리 · servers 칸에 source 가 있어도(openbao-audit · files) 올리는 이름 'idp-server' 를 덮지 않는다(#72 교훈)."""
    _inv(monkeypatch, INVENTORY)
    nano = _ago(118).replace("+00:00", ".018595764Z")
    head = {"written_at": _ago(20), "host": "idp-host", "interval_seconds": 60, "window_days": 14, "source": "openbao-audit",
            "read_ok": True, "why": None, "files_read": 15, "lines_read": 2600, "bad_lines": 0, "reports": 173,
            "servers": [{"server": "srv-a", "gw": "gw-a", "env": "dev", "service": "svc-a", "host": "host-a",  # IdP 모양 그대로
                         "last_read_at": nano, "read_ok": True, "why": None, "source": "files", "files_read": 3, "lines_read": 128221},
                        {"server": "srv-b", "gw": "gw-a", "env": "dev", "service": "svc-a", "host": "host-b",
                         "last_read_at": _ago(118), "read_ok": False,
                         "why": "/var/log/auth.log 를 읽을 권한이 없다 (ubuntu 가 adm 그룹인가)", "source": None,
                         "files_read": 0, "lines_read": 0},
                        {"server": "srv-s", "gw": "gw-s", "env": "stg", "service": "svc-a", "host": "host-s",
                         "last_read_at": _ago(11 * 60), "read_ok": True, "why": None, "source": "files", "files_read": 1,
                         "lines_read": 40},
                        "깨진 칸"],
            "events": 4, "truncated": False}  # 깨진 줄 1 포함 4줄
    linked = {**LOGIN_NEW, "at": "2026-10-28T23:59:01.652873123Z", "issued_at": "2026-10-28T23:58:56.834689981Z"}
    again = {**linked, "at": "2026-10-29T00:05:00.000000001Z"}  # 같은 인증서로 두 번째 접속
    _upload_from_file(client, _file(tmp_path, [head, again, linked, "{깨진 줄", LOGIN_OLD]))

    with SessionLocal() as db:  # 먼저 — 'idp-server' 줄에 실제로 들어갔고, 파일의 source 로 새 줄이 생기지 않음
        rows = db.query(AccessLogSnapshot).all()
        assert [r.source for r in rows] == ["idp-server"] and len(json.loads(rows[0].events)) == 3
    s = _get(client)
    assert s["state"] == "ok", s["reasons"]
    assert (s["files_read"], s["lines_read"], s["reports"]) == (15, 2600, 173)
    assert [e["at"] for e in s["events"]] == ["2026-10-29T00:05:00.000000Z", "2026-10-28T23:59:01.652873Z",
                                              "2026-10-28T10:00:00.000000Z"]
    assert [e["serial"] for e in s["events"][:2]] == ["3560879729764d4"] * 2  # 한 인증서로 여러 번
    assert s["events"][0]["issued_at"] == "2026-10-28T23:58:56.834689Z" and s["events"][2]["issued_at"] is None
    by = {_key(x): x for x in s["servers"]}
    assert {k: (by[k]["state"], by[k]["link"]) for k in by} == {
        "gw-a:srv-a": ("ok", "listed"), "gw-a:srv-b": ("failed", "listed"), "gw-s:srv-s": ("stale", "listed"),
        "-:srv-new": ("silent", "listed")}
    assert by["gw-a:srv-b"]["reason"] == "그 서버 기록 못 읽음 — /var/log/auth.log 를 읽을 권한이 없다 (ubuntu 가 adm 그룹인가)"
    assert by["gw-a:srv-a"]["host"] == "host-a" and by["gw-a:srv-a"]["lines_read"] == 128221
    assert s["reading"] == 1 and s["notes"] == ["깨져서 뺀 줄 1개", "깨져서 뺀 서버 읽기 칸 1개"]


def test_collector_missing_file_end_to_end_is_unknown_not_empty(client, local, tmp_path):
    """파일이 없다 — 수집기는 건너뛰지 않고 '못 봄 + 이유' 를 올리고, 화면은 빈 표가 아니라 모름."""
    _upload_from_file(client, str(tmp_path / "server-logins.jsonl"))
    with SessionLocal() as db:
        r = db.query(AccessLogSnapshot).filter_by(source="idp-server").one()  # 올라오긴 했다
        assert (r.read_ok, r.read_error) == (False, "파일 없음")
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"][0].startswith("못 봄 — 요약 파일이 없어요")
    assert s["events"] == [] and s["servers"] == []


def test_collector_header_read_ok_false_end_to_end_is_unknown_with_why(client, local, tmp_path):
    head = {"written_at": _ago(20), "interval_seconds": 60, "source": "openbao-audit", "read_ok": False,
            "why": "금고 감사 기록 폴더가 없음", "files_read": 0, "servers": [], "events": 0}
    _upload_from_file(client, _file(tmp_path, [head]))
    s = _get(client)
    assert s["state"] == "unknown" and s["reasons"] == ["못 봄 — IdP 가 금고 기록을 못 읽음: 금고 감사 기록 폴더가 없음"]
    assert s["servers"] == []
