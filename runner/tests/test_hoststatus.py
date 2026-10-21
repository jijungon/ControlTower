"""서버 상태 파일 읽기 — 못 읽는 경우마다 이유를 남기고(read_ok=False), 예외로 수집기를 멈추지 않는다."""
import json
import os
import types

import pytest

from runner.hoststatus import read_status, summary

GOOD = {
    "written_at": "2026-10-20T08:00:22+00:00", "host": "test-host", "interval_seconds": 60, "ok": False,
    "problems": ["systemd 실패: a.service"], "unread": ["breakglass: 계정이 없다"],
    "signals": {"disk": [{"mount": "/", "read": True, "used_pct": 22.6}]},
}


def _write(tmp_path, data, name="status.json"):
    p = tmp_path / name
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(p)


def test_reads_the_file_as_is(tmp_path):
    s = read_status(_write(tmp_path, GOOD))
    assert s["read_ok"] is True and s["read_error"] is None
    assert (s["ok"], s["problems"], s["unread"], s["host"], s["interval_seconds"]) == (
        False, ["systemd 실패: a.service"], ["breakglass: 계정이 없다"], "test-host", 60,
    )
    assert summary(s) == "경보(문제 1 · 못 본 것 1)"
    ok = read_status(_write(tmp_path, {**GOOD, "ok": True, "problems": [], "unread": []}))
    assert summary(ok) == "정상"


@pytest.mark.parametrize(
    "content, why",
    [
        (None, "파일 없음"),
        ("{깨진 json", "JSON 이 깨짐"),
        ("[1, 2]", "JSON 모양이 다름(객체가 아님)"),
        ({"ok": True, "problems": []}, "필수 칸 없음: written_at, unread"),
        ({**GOOD, "ok": "yes"}, "칸 모양이 다름(ok 는 참/거짓, problems · unread 는 목록)"),
        ({**GOOD, "unread": "없음"}, "칸 모양이 다름(ok 는 참/거짓, problems · unread 는 목록)"),
    ],
)
def test_cannot_read_is_unknown_with_reason(tmp_path, content, why):
    path = str(tmp_path / "status.json") if content is None else _write(tmp_path, content)
    s = read_status(path)
    assert s == {"read_ok": False, "read_error": why}
    assert summary(s) == f"모름({why})"


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한과 상관없이 읽음")
def test_no_permission_is_unknown(tmp_path):
    p = _write(tmp_path, GOOD)
    os.chmod(p, 0)
    try:
        assert read_status(p) == {"read_ok": False, "read_error": "권한 없음"}
    finally:
        os.chmod(p, 0o600)


def test_missing_interval_falls_back_to_one_minute(tmp_path):
    s = read_status(_write(tmp_path, {**GOOD, "interval_seconds": "60"}))
    assert s["interval_seconds"] == 60
    s = read_status(_write(tmp_path, {k: v for k, v in GOOD.items() if k != "interval_seconds"}))
    assert s["interval_seconds"] == 60


def test_agent_uploads_status_each_round_and_skips_when_off(monkeypatch, tmp_path):
    """수집기 — 켜져 있으면 요청 확인 전에 상태를 올리고(못 읽어도 이유를 올림), 경로가 비면 아무것도 안 함."""
    import runner.cli as cli

    sent: list = []

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_host_status(self, source, reader, snap):
            sent.append((source, reader, snap))
            return {"ok": True}

        def claim_collect(self, *a, **k):
            return None

        def close(self):
            pass

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    cfg = types.SimpleNamespace(central_url="x", api_token="t", runner_name="test-collector", idp_status_file=_write(tmp_path, GOOD))
    cli.cmd_agent(cfg, once=True)
    assert sent[0][0:2] == ("idp", "test-collector") and sent[0][2]["read_ok"] is True and sent[0][2]["problems"]

    sent.clear()
    cfg.idp_status_file = str(tmp_path / "없는파일.json")
    cli.cmd_agent(cfg, once=True)
    assert sent[0][2] == {"read_ok": False, "read_error": "파일 없음"}  # 못 읽은 것도 올림 → 화면에 '모름'

    sent.clear()
    cfg.idp_status_file = ""
    cli.cmd_agent(cfg, once=True)
    assert sent == []  # 꺼짐
