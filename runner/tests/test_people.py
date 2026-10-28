"""사람 이름표 파일 읽기 — 못 읽으면 이유를 남기고(read_ok=False), 깨진 줄은 빼되 세고, 수집기를 멈추지 않는다.

모양은 IdP 쪽이 정한 그대로(IdP 1e2f581 · 49034c6): 머리 한 줄 + 사람 한 줄씩(이메일 순, 이메일 없는 사람은 맨 뒤).
"""
import json
import types

import pytest

from runner.people import read_people, summary

HEAD = {"written_at": "2026-10-28T06:47:01+00:00", "host": "idp-host", "interval_seconds": 300, "source": "authentik",
        "read_ok": True, "why": None, "groups": {"server-admin": 3, "developer": 1}, "people": 4}
OPS = {"email": "ops@example.com", "username": "ops", "name": "Ops Person", "groups": ["server-admin"], "active": True}
ADMIN = {"email": "root@example.com", "username": "akadmin", "name": "Default Admin", "groups": ["server-admin"], "active": True}
DEV = {"email": "dev@example.com", "username": "dev1", "name": "", "groups": ["developer"], "active": True}
GONE = {"email": None, "username": "left", "name": "Left Company", "groups": ["server-admin"], "active": False}


def _write(tmp_path, lines, name="people.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return str(p)


def test_reads_header_and_people_as_the_idp_writes_them(tmp_path):
    s = read_people(_write(tmp_path, [HEAD, DEV, OPS, ADMIN, GONE, ""]))
    assert s["read_ok"] is True and s["read_error"] is None
    assert {k: s[k] for k in ("written_at", "host", "interval_seconds", "origin", "list_ok", "list_reason", "groups",
                              "header_people", "person_lines", "bad_lines", "truncated")} == {
        "written_at": "2026-10-28T06:47:01+00:00", "host": "idp-host", "interval_seconds": 300, "origin": "authentik",
        "list_ok": True, "list_reason": None, "groups": {"server-admin": 3, "developer": 1}, "header_people": 4,
        "person_lines": 4, "bad_lines": 0, "truncated": False}
    assert s["people"] == [
        {"email": "dev@example.com", "username": "dev1", "name": None, "groups": ["developer"], "active": True},  # 빈 이름 → None
        {"email": "ops@example.com", "username": "ops", "name": "Ops Person", "groups": ["server-admin"], "active": True},
        {"email": "root@example.com", "username": "akadmin", "name": "Default Admin", "groups": ["server-admin"], "active": True},
        {"email": None, "username": "left", "name": "Left Company", "groups": ["server-admin"], "active": False},  # 막힌 계정도 줄은 남음
    ]
    assert "source" not in s, "파일의 source 를 그 이름 그대로 두면 올릴 때 'idp' 를 덮을 수 있다(#72)"
    assert len(s["digest"]) == 64
    assert summary(s) == "4명"


def test_email_is_the_key_so_it_is_lower_cased_and_trimmed(tmp_path):
    s = read_people(_write(tmp_path, [HEAD, {**OPS, "email": "  Ops@Example.COM "}]))
    assert s["people"][0]["email"] == "ops@example.com"


def test_idp_could_not_read_authentik_keeps_why_and_no_people(tmp_path):
    # IdP 규칙: 못 읽으면 read_ok=false · why · 사람 줄 0줄 · groups=null(0 이 아님)
    head = {**HEAD, "read_ok": False, "why": "authentik api: 503", "groups": None, "people": 0}
    s = read_people(_write(tmp_path, [head]))
    assert s["read_ok"] is True  # 파일은 읽었다
    assert (s["list_ok"], s["list_reason"], s["groups"], s["people"]) == (False, "authentik api: 503", None, [])
    assert summary(s) == "이름 모름(IdP 가 Authentik 을 못 읽음 — authentik api: 503)"


def test_broken_person_lines_are_left_out_but_counted(tmp_path):
    s = read_people(_write(tmp_path, [
        HEAD, OPS, "{깨진 줄", {**DEV, "active": "yes"}, {"username": None, "email": None, "active": True}, [1, 2], DEV,
    ]))
    assert [p["email"] for p in s["people"]] == ["ops@example.com", "dev@example.com"]
    assert (s["bad_lines"], s["person_lines"]) == (4, 6)
    assert summary(s) == "2명 · 깨진 줄 4"


def test_odd_groups_counts_are_unknown_not_zero(tmp_path):
    s = read_people(_write(tmp_path, [{**HEAD, "groups": {"server-admin": "three"}}, OPS]))
    assert s["groups"] is None


@pytest.mark.parametrize("lines,why", [
    (None, "파일 없음"),
    ([], "빈 파일"),
    (["{머리 깨짐"], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),
    ([{"host": "x", "read_ok": True}], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),
    ([{"written_at": "x", "read_ok": "yes"}], "첫 줄(머리)이 깨짐 — written_at · read_ok 필요"),
])
def test_cannot_read_is_unknown_with_reason(tmp_path, lines, why):
    path = str(tmp_path / "없음.jsonl") if lines is None else _write(tmp_path, lines)
    s = read_people(path)
    assert s == {"read_ok": False, "read_error": why, "people": [], "bad_lines": 0}
    assert summary(s) == f"이름 모름({why})"


def test_directory_and_bad_utf8_are_reasons_not_crashes(tmp_path):
    assert read_people(str(tmp_path))["read_error"] == "파일이 아니라 폴더"
    p = tmp_path / "bad.jsonl"
    p.write_bytes(b"\xff\xfe\x00")
    assert read_people(str(p))["read_error"] == "글자가 깨짐(UTF-8 아님)"


class _Stop(Exception):
    pass


def _fake_api(sent):
    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_people(self, source, reader, snap):
            sent.append((source, reader, snap))
            return {"ok": True}

        def claim_collect(self, *a, **k):
            return None

        def close(self):
            pass

    return FakeAPI


def _cfg(path):
    return types.SimpleNamespace(central_url="x", api_token="t", runner_name="test-collector", idp_status_file="",
                                 idp_access_file="", idp_people_file=path)


def test_agent_uploads_and_reason_when_missing_and_skips_when_off(monkeypatch, tmp_path):
    import runner.cli as cli

    sent: list = []
    monkeypatch.setattr(cli, "CentralAPI", _fake_api(sent))
    cli.cmd_agent(_cfg(_write(tmp_path, [HEAD, OPS])), once=True)
    assert sent[0][0:2] == ("idp", "test-collector") and sent[0][2]["read_ok"] is True and len(sent[0][2]["people"]) == 1

    sent.clear()
    cli.cmd_agent(_cfg(str(tmp_path / "없는파일.jsonl")), once=True)
    assert sent[0][2]["read_ok"] is False and sent[0][2]["read_error"] == "파일 없음"  # 못 읽은 것도 올림 → '이름 모름'

    sent.clear()
    cli.cmd_agent(_cfg(""), once=True)
    assert sent == []  # 꺼짐


def test_agent_does_not_resend_unchanged_file_every_round(monkeypatch, tmp_path):
    """5초마다 돌아도 내용이 그대로면 1분 안에는 다시 안 올림 — 바뀌면 바로 올림."""
    import runner.cli as cli

    sent: list = []
    monkeypatch.setattr(cli, "CentralAPI", _fake_api(sent))
    path = tmp_path / "people.jsonl"
    path.write_text(json.dumps(HEAD) + "\n" + json.dumps(OPS) + "\n", encoding="utf-8")
    rounds = {"n": 0}

    def fake_sleep(_):
        rounds["n"] += 1
        if rounds["n"] == 2:  # 세 번째 바퀴 전에 내용이 바뀜
            path.write_text(json.dumps({**HEAD, "written_at": "2026-10-28T06:52:01+00:00"}) + "\n", encoding="utf-8")
        if rounds["n"] == 4:
            raise _Stop

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        cli.cmd_agent(_cfg(str(path)))
    assert [s[2]["written_at"] for s in sent] == ["2026-10-28T06:47:01+00:00", "2026-10-28T06:52:01+00:00"]


def test_upload_keeps_our_source_even_if_the_file_has_one():
    # 읽은 내용에 source · reader 가 있어도 올리는 이름('idp' · 수집기 이름)이 이긴다(#72 와 같은 까닭)
    import httpx

    from runner.api import CentralAPI

    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    api = CentralAPI("http://central", "t")
    api._client = httpx.Client(base_url="http://central", transport=httpx.MockTransport(handler))
    api.upload_people("idp", "collector-1", {"source": "authentik", "reader": "file", "read_ok": True, "digest": "x", "people": []})
    assert [(p, b["source"], b["reader"]) for p, b in sent] == [("/api/idp-people", "idp", "collector-1")]
    assert "digest" not in sent[0][1]
