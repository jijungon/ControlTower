"""접속 점검 분류기(classify) + 대상 필터(_select) 단위 테스트."""
from runner.cli import _select
from runner.probe import classify


def test_classify_ok():
    r = classify(0, "")
    assert r["ok"] is True and r["needs_2fa"] is False


def test_classify_2fa_partial_success():
    r = classify(255, 'debug1: Authenticated using "publickey" with partial success.\nPermission denied (keyboard-interactive).')
    assert r["ok"] is False and r["needs_2fa"] is True


def test_classify_keyboard_interactive_denied():
    r = classify(255, "Permission denied (publickey,keyboard-interactive).")
    assert r["needs_2fa"] is True


def test_classify_network_fail():
    assert classify(255, "ssh: connect to host x port 22: Connection refused")["needs_2fa"] is False
    assert classify(255, "ssh: connect to host x port 22: Operation timed out")["ok"] is False


def test_classify_key_denied():
    r = classify(255, "Permission denied (publickey).")
    assert r["ok"] is False and r["needs_2fa"] is False


def test_select_filter():
    servers = [
        {"hostname": "a", "group": "control"},
        {"hostname": "b", "group": "battery"},
        {"hostname": "c", "group": "control"},
    ]
    assert [s["hostname"] for s in _select(servers, "control", None)] == ["a", "c"]
    assert [s["hostname"] for s in _select(servers, None, "b")] == ["b"]
    assert len(_select(servers, None, None)) == 3
