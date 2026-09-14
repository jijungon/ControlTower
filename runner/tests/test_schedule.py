"""주기 수집(all) 오케스트레이션 테스트 — 실제 수집기는 monkeypatch."""
import types

import runner.cli as cli

STEPS = ["cmd_import", "cmd_test", "cmd_conf", "cmd_updates", "cmd_versions", "cmd_versions_repo", "cmd_cicd"]


def _record_all(monkeypatch, calls, failing=None):
    for fn in STEPS:
        label = fn.removeprefix("cmd_")

        def make(label):
            def _rec(cfg):
                if failing and label == failing:
                    raise RuntimeError("boom")
                calls.append(label)
            return _rec

        monkeypatch.setattr(cli, fn, make(label))


def test_run_all_once_without_gitlab(monkeypatch):
    calls: list[str] = []
    _record_all(monkeypatch, calls)
    cli.run_all_once(types.SimpleNamespace(gitlab_url="", gitlab_token=""))
    assert calls == ["import", "test", "conf", "updates", "versions"]  # GitLab 스텝 제외


def test_run_all_once_with_gitlab(monkeypatch):
    calls: list[str] = []
    _record_all(monkeypatch, calls)
    cli.run_all_once(types.SimpleNamespace(gitlab_url="http://gl", gitlab_token="tok"))
    assert calls == ["import", "test", "conf", "updates", "versions", "versions_repo", "cicd"]


def test_step_failure_isolated(monkeypatch):
    calls: list[str] = []
    _record_all(monkeypatch, calls, failing="conf")  # conf 실패
    cli.run_all_once(types.SimpleNamespace(gitlab_url="", gitlab_token=""))
    # conf 는 기록 안 되지만 이후 스텝(updates/versions)은 계속
    assert calls == ["import", "test", "updates", "versions"]
