"""금고 접속 기록 요약 파일 읽기 — 못 읽으면 이유를 남기고(read_ok=False), 깨진 줄은 빼되 세고, 수집기를 멈추지 않는다.

모양은 IdP 쪽이 정한 그대로(IdP 557ab6c): 머리 한 줄 + 인증서 발급 한 건씩(최신순), 시각은 나노초까지.
"""
import json
import types
from datetime import datetime

import pytest

from runner.accesslog import read_access, summary

HEAD = {"written_at": "2026-10-28T02:00:00Z", "host": "idp-host", "interval_seconds": 60, "window_days": 14,
        "source": "openbao-audit", "read_ok": True, "why": None, "files_read": 3, "lines_read": 812,
        "bad_lines": 1, "events": 4, "truncated": False}
EV_PERSON = {"at": "2026-10-28T01:20:03.123456789Z", "kind": "person", "who": "dev@example.com", "env": "prod",
             "account": "ubuntu", "role": "prod-ubuntu", "serial": "11d1bda82b498807", "result": "denied",
             "reason": "1 error occurred:\n\t* permission denied\n\n"}
EV_GW = {"at": "2026-10-28T01:10:00.5Z", "kind": "person", "who": "dev@example.com", "env": "dev", "account": None,
         "role": "dev-gw", "serial": None, "result": "issued", "reason": None}
EV_MACHINE = {"at": "2026-10-27T09:00:00Z", "kind": "machine", "who": "runner", "env": "dev", "account": "appuser",
              "role": "dev-runner", "serial": None, "result": "issued", "reason": None}
EV_OTHER = {"at": "2026-10-27T08:00:00.000000001Z", "kind": "other", "who": None, "env": "stg", "account": "ubuntu",
            "role": "list", "serial": None, "result": "issued", "reason": None}  # 이상한 역할 이름도 그대로


def _write(tmp_path, lines, name="access.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return str(p)


def test_reads_header_and_events_as_the_idp_writes_them(tmp_path):
    s = read_access(_write(tmp_path, [HEAD, EV_PERSON, EV_GW, "{깨진 줄", EV_MACHINE, EV_OTHER, ""]))
    assert s["read_ok"] is True and s["read_error"] is None
    assert {k: s[k] for k in ("written_at", "host", "interval_seconds", "window_days", "audit_ok", "audit_reason",
                              "files_read", "lines_read", "source_bad_lines", "header_events", "truncated")} == {
        "written_at": "2026-10-28T02:00:00Z", "host": "idp-host", "interval_seconds": 60, "window_days": 14,
        "audit_ok": True, "audit_reason": None, "files_read": 3, "lines_read": 812,
        "source_bad_lines": 1, "header_events": 4, "truncated": False}
    assert "source" not in s  # 파일의 source('openbao-audit')는 안 싣는다 — 올릴 때 'idp' 를 덮어썼다(10-28 운영)
    assert [e["kind"] for e in s["events"]] == ["person", "person", "machine", "other"]
    assert s["events"][1]["account"] is None and s["events"][1]["role"] == "dev-gw"  # 개인 gw 계정
    assert s["events"][3]["who"] is None  # 이름 없는 기록도 버리지 않음
    assert s["bad_lines"] == 1 and s["event_lines"] == 5  # 머리는 4건이라는데 5줄(깨진 1 포함) — 중앙이 알림
    assert summary(s) == "4건 · 깨진 줄 1"
    assert s["digest"] != read_access(_write(tmp_path, [HEAD, EV_PERSON]))["digest"]  # 내용이 바뀌면 지문도 바뀜


def test_nanosecond_times_are_cut_to_microseconds_so_python_can_read_them(tmp_path):
    s = read_access(_write(tmp_path, [HEAD, EV_PERSON, EV_OTHER]))
    assert [e["at"] for e in s["events"]] == ["2026-10-28T01:20:03.123456Z", "2026-10-27T08:00:00.000000Z"]
    for e in s["events"]:
        datetime.fromisoformat(e["at"].replace("Z", "+00:00"))  # 읽힘
    bad = read_access(_write(tmp_path, [HEAD, {**EV_PERSON, "at": "어제"}, {**EV_PERSON, "at": None}]))
    assert bad["events"] == [] and bad["bad_lines"] == 2  # 시각을 못 읽는 줄은 깨진 줄로 셈


def test_audit_not_read_keeps_why(tmp_path):
    s = read_access(_write(tmp_path, [{**HEAD, "read_ok": False, "why": "감사 기록이 비어 있다 — 0줄", "events": 0}]))
    assert s["read_ok"] is True and s["audit_ok"] is False and s["audit_reason"] == "감사 기록이 비어 있다 — 0줄"
    assert summary(s) == "못 봄(IdP 가 금고 기록을 못 읽음 — 감사 기록이 비어 있다 — 0줄)"


def test_old_header_without_counts_is_still_read(tmp_path):
    old = read_access(_write(tmp_path, [{"written_at": "2026-10-28T02:00:00Z", "read_ok": True}]))
    assert (old["read_ok"], old["files_read"], old["lines_read"], old["header_events"], old["truncated"]) == (True, None, None, None, False)


@pytest.mark.parametrize(
    "lines, why",
    [
        (None, "파일 없음"),
        ([""], "빈 파일"),
        (["{깨진 머리"], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),
        ([{"written_at": "2026-10-28T02:00:00Z"}], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),
        ([EV_PERSON, EV_GW], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),  # 머리 없이 이벤트부터 — '0건' 이 아니라 못 봄
    ],
)
def test_cannot_read_is_unknown_with_reason(tmp_path, lines, why):
    path = str(tmp_path / "access.jsonl") if lines is None else _write(tmp_path, lines)
    s = read_access(path)
    assert s == {"read_ok": False, "read_error": why, "events": [], "bad_lines": 0}
    assert summary(s) == f"못 봄({why})"


class _Stop(Exception):
    pass


def _fake_api(sent):
    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_access_log(self, source, reader, snap):
            sent.append((source, reader, snap))
            return {"ok": True}

        def claim_collect(self, *a, **k):
            return None

        def close(self):
            pass

    return FakeAPI


def test_agent_uploads_and_reason_when_missing_and_skips_when_off(monkeypatch, tmp_path):
    import runner.cli as cli

    sent: list = []
    monkeypatch.setattr(cli, "CentralAPI", _fake_api(sent))
    path = _write(tmp_path, [HEAD, EV_PERSON])
    cfg = types.SimpleNamespace(central_url="x", api_token="t", runner_name="test-collector", idp_status_file="", idp_access_file=path)
    cli.cmd_agent(cfg, once=True)
    assert sent[0][0:2] == ("idp", "test-collector") and sent[0][2]["read_ok"] is True and len(sent[0][2]["events"]) == 1

    sent.clear()
    cfg.idp_access_file = str(tmp_path / "없는파일.jsonl")  # IdP 반영 전 — 파일이 아직 없음
    cli.cmd_agent(cfg, once=True)
    assert sent[0][2]["read_ok"] is False and sent[0][2]["read_error"] == "파일 없음"  # 못 읽은 것도 올림 → '못 봄'

    sent.clear()
    cfg.idp_access_file = ""
    cli.cmd_agent(cfg, once=True)
    assert sent == []  # 꺼짐


def test_agent_does_not_resend_unchanged_file_every_round(monkeypatch, tmp_path):
    """5초마다 돌아도 내용이 그대로면 1분 안에는 다시 안 올림 — 바뀌면 바로 올림."""
    import runner.cli as cli

    sent: list = []
    monkeypatch.setattr(cli, "CentralAPI", _fake_api(sent))
    path = tmp_path / "access.jsonl"
    path.write_text(json.dumps(HEAD) + "\n" + json.dumps(EV_PERSON) + "\n", encoding="utf-8")
    rounds = {"n": 0}

    def fake_sleep(_):
        rounds["n"] += 1
        if rounds["n"] == 2:  # 세 번째 바퀴 전에 내용이 바뀜
            path.write_text(json.dumps({**HEAD, "written_at": "2026-10-28T02:01:00Z"}) + "\n", encoding="utf-8")
        if rounds["n"] == 4:
            raise _Stop

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    cfg = types.SimpleNamespace(central_url="x", api_token="t", runner_name="c", idp_status_file="", idp_access_file=str(path))
    with pytest.raises(_Stop):
        cli.cmd_agent(cfg)
    assert [s[2]["written_at"] for s in sent] == ["2026-10-28T02:00:00Z", "2026-10-28T02:01:00Z"]


def test_upload_keeps_our_source_even_if_the_file_has_one():
    # 읽은 내용에 source · reader 가 있어도 올리는 이름('idp' · 수집기 이름)이 이긴다 — 10-28 운영에서
    # 파일 머리의 source('openbao-audit')가 'idp' 를 덮어 중앙이 늘 '연결 전' 이었다
    import httpx

    from runner.api import CentralAPI

    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    api = CentralAPI("http://central", "t")
    api._client = httpx.Client(base_url="http://central", transport=httpx.MockTransport(handler))
    snap = {"source": "openbao-audit", "reader": "file", "read_ok": True, "digest": "x", "events": []}
    api.upload_access_log("idp", "collector-1", snap)
    api.upload_host_status("idp", "collector-1", {"source": "file", "reader": "file", "read_ok": True})
    assert [(p, b["source"], b["reader"]) for p, b in sent] == [
        ("/api/access-log", "idp", "collector-1"),
        ("/api/host-status", "idp", "collector-1"),
    ]
    assert "digest" not in sent[0][1]


# ── 2단계: gw-logins.jsonl — gw 에 실제로 들어간 기록(IdP 7159c7f) ─────────────

from runner.accesslog import gw_summary, read_gw_logins  # noqa: E402

GW_HEAD = {**HEAD, "events": 3, "reports": 5,
           "gws": [{"gw": "gw-shop-dev", "host": "shop-gw-1", "last_report_at": "2026-10-28T05:20:00.123456789Z",
                    "every_seconds": 300, "read_ok": True, "why": None, "source": "journal", "files_read": 1, "lines_read": 77},
                   {"gw": "gw-shop-stg", "host": "shop-gw-2", "last_report_at": "2026-10-28T05:19:00Z", "every_seconds": 300,
                    "read_ok": False, "why": "auth.log 권한 없음", "source": "auth.log", "files_read": 0, "lines_read": 0},
                   {"host": "이름 없는 gw"}, "깨진 칸"]}
LOGIN = {"at": "2026-10-28T05:21:38.619202123Z", "gw": "gw-shop-dev", "account": "ubuntu", "kind": "person",
         "who": "ops@example.com", "serial": "776cb41cedacd9d8", "issued_at": "2026-10-28T05:04:58.434246277Z",
         "env": "dev", "role": "dev-ubuntu"}
LOGIN_NO_ISSUE = {"at": "2026-10-27T01:00:00Z", "gw": "gw-shop-stg", "account": "dev1", "kind": "robot", "who": None,
                  "serial": "0a0b0c0d0e0f1011", "issued_at": None, "env": None, "role": None}


def test_gw_logins_reads_header_gws_and_logins_as_the_idp_writes_them(tmp_path):
    s = read_gw_logins(_write(tmp_path, [GW_HEAD, LOGIN, "{깨진 줄", {**LOGIN, "gw": ""}, LOGIN_NO_ISSUE], "gw-logins.jsonl"))
    assert s["read_ok"] is True and s["audit_ok"] is True and (s["files_read"], s["lines_read"], s["reports"]) == (3, 812, 5)
    assert "source" not in s  # 머리의 source('openbao-audit')는 안 싣는다 — 올리는 이름을 덮지 않게
    assert s["gws"] == [
        {"gw": "gw-shop-dev", "host": "shop-gw-1", "last_report_at": "2026-10-28T05:20:00.123456Z", "every_seconds": 300,
         "read_ok": True, "why": None, "log_source": "journal", "files_read": 1, "lines_read": 77},
        {"gw": "gw-shop-stg", "host": "shop-gw-2", "last_report_at": "2026-10-28T05:19:00Z", "every_seconds": 300,
         "read_ok": False, "why": "auth.log 권한 없음", "log_source": "auth.log", "files_read": 0, "lines_read": 0},
    ]
    assert all("source" not in g for g in s["gws"])  # gw 의 source 도 이름을 바꿔 싣는다(log_source)
    assert s["bad_gws"] == 2  # gw 이름 없는 칸 · 깨진 칸 — 버리지 않고 셈
    assert s["events"] == [
        {"at": "2026-10-28T05:21:38.619202Z", "gw": "gw-shop-dev", "account": "ubuntu", "kind": "person",
         "who": "ops@example.com", "serial": "776cb41cedacd9d8", "issued_at": "2026-10-28T05:04:58.434246Z",
         "env": "dev", "role": "dev-ubuntu"},
        {"at": "2026-10-27T01:00:00Z", "gw": "gw-shop-stg", "account": "dev1", "kind": "other", "who": None,
         "serial": "0a0b0c0d0e0f1011", "issued_at": None, "env": None, "role": None},  # 발급 기록 못 찾음 · 모르는 kind 는 other
    ]
    assert s["bad_lines"] == 2 and s["event_lines"] == 4  # 깨진 줄 · gw 없는 줄
    assert gw_summary(s) == "2번 · 보고한 gw 2대 · 깨진 줄 2"
    for e in s["events"]:
        datetime.fromisoformat(e["at"].replace("Z", "+00:00"))  # 나노초도 읽힘


def test_gw_logins_header_without_gws_is_unknown_not_empty(tmp_path):
    old = {k: v for k, v in GW_HEAD.items() if k != "gws"}
    s = read_gw_logins(_write(tmp_path, [old, LOGIN], "gw-logins.jsonl"))
    assert s["gws"] is None and s["bad_gws"] == 0  # 빈 목록([])이 아니라 모름(None) — 중앙이 '보고 안 함' 으로 그리지 않게
    assert gw_summary(s) == "1번 · 보고한 gw 모름"
    s = read_gw_logins(_write(tmp_path, [{**GW_HEAD, "gws": "깨짐"}, LOGIN], "gw-logins.jsonl"))
    assert s["gws"] is None


def test_gw_logins_cannot_read_keeps_reason(tmp_path):
    s = read_gw_logins(str(tmp_path / "gw-logins.jsonl"))  # IdP 반영 전 — 파일 없음
    assert s == {"read_ok": False, "read_error": "파일 없음", "events": [], "bad_lines": 0}
    assert gw_summary(s) == "못 봄(파일 없음)"
    s = read_gw_logins(_write(tmp_path, [{**GW_HEAD, "read_ok": False, "why": "감사 기록 없음"}], "gw-logins.jsonl"))
    assert s["audit_ok"] is False and gw_summary(s) == "못 봄(IdP 가 금고 기록을 못 읽음 — 감사 기록 없음)"


def _fake_api_gw(sent):
    class FakeAPI(_fake_api(sent)):
        def upload_gw_logins(self, source, reader, snap):
            sent.append((source, reader, snap))
            return {"ok": True}

    return FakeAPI


def test_agent_uploads_gw_logins_and_reason_when_missing(monkeypatch, tmp_path):
    import runner.cli as cli

    sent: list = []
    monkeypatch.setattr(cli, "CentralAPI", _fake_api_gw(sent))
    path = _write(tmp_path, [GW_HEAD, LOGIN], "gw-logins.jsonl")
    cfg = types.SimpleNamespace(central_url="x", api_token="t", runner_name="test-collector", idp_status_file="",
                                idp_access_file=_write(tmp_path, [HEAD, EV_PERSON]), idp_gw_logins_file=path)
    cli.cmd_agent(cfg, once=True)
    assert [(s[0], s[1], len(s[2]["events"])) for s in sent] == [("idp", "test-collector", 1), ("idp-gw", "test-collector", 1)]

    sent.clear()
    cfg.idp_access_file = ""
    cfg.idp_gw_logins_file = str(tmp_path / "없는파일.jsonl")  # IdP 반영 전 — 건너뛰지 않고 '못 봄' 을 올림
    cli.cmd_agent(cfg, once=True)
    assert [(s[0], s[2]["read_ok"], s[2]["read_error"]) for s in sent] == [("idp-gw", False, "파일 없음")]

    sent.clear()
    cfg.idp_gw_logins_file = ""
    cli.cmd_agent(cfg, once=True)
    assert sent == []  # 꺼짐


def test_gw_upload_keeps_our_source_even_if_the_file_has_one():
    import httpx

    from runner.api import CentralAPI

    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    api = CentralAPI("http://central", "t")
    api._client = httpx.Client(base_url="http://central", transport=httpx.MockTransport(handler))
    api.upload_gw_logins("idp-gw", "collector-1", {"source": "openbao-audit", "reader": "file", "read_ok": True, "digest": "x"})
    assert [(p, b["source"], b["reader"]) for p, b in sent] == [("/api/access-log/gw-logins", "idp-gw", "collector-1")]
    assert "digest" not in sent[0][1]
