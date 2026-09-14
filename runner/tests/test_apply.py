"""conf 적용(applier) 단위 테스트 — ssh/verify 는 monkeypatch(실서버 불필요)."""
import runner.applier as ap


class FakeR:
    def __init__(self, rc=0, stderr=""):
        self.returncode = rc
        self.stderr = stderr
        self.stdout = ""


def test_apply_success_sequence(monkeypatch):
    cmds = []

    def fake_ssh(alias, command, timeout, input=None):
        cmds.append((command, input))
        return FakeR(0)

    monkeypatch.setattr(ap, "_ssh", fake_ssh)
    monkeypatch.setattr(ap, "read_file", lambda alias, path, timeout: ("new\n", None))

    res = ap.apply_intent("web-01", "/etc/x", "new\n", ap._sha("new\n"), sudo=False, ts="TS")
    assert res["ok"] is True
    assert res["backup_path"] == "/etc/x.ct-backup-TS"
    seq = [c for c, _ in cmds]
    assert seq[0] == "cp -- /etc/x /etc/x.ct-backup-TS"     # 백업 먼저
    assert seq[1] == "tee -- /etc/x.ct-new-TS > /dev/null"  # 임시파일 쓰기
    assert cmds[1][1] == "new\n"                            # stdin = 새 내용
    assert seq[2] == "mv -- /etc/x.ct-new-TS /etc/x"        # 원자적 교체


def test_apply_sudo_prefix(monkeypatch):
    cmds = []
    monkeypatch.setattr(ap, "_ssh", lambda a, c, t, input=None: cmds.append(c) or FakeR(0))
    monkeypatch.setattr(ap, "read_file", lambda a, p, t: ("new\n", None))
    ap.apply_intent("h", "/etc/x", "new\n", ap._sha("new\n"), sudo=True, ts="TS")
    assert cmds[0].startswith("sudo cp -- ")
    assert cmds[1].startswith("sudo tee -- ")
    assert cmds[2].startswith("sudo mv -- ")


def test_apply_write_failure_no_replace(monkeypatch):
    cmds = []

    def fake_ssh(a, c, t, input=None):
        cmds.append(c)
        return FakeR(1, "permission denied") if c.startswith("tee") else FakeR(0)

    monkeypatch.setattr(ap, "_ssh", fake_ssh)
    res = ap.apply_intent("h", "/etc/x", "new\n", "sha", sudo=False, ts="TS")
    assert res["ok"] is False and "write" in res["error"]
    assert not any(c.startswith("mv") for c in cmds)   # 교체 안 함(백업만 존재)
    assert res["backup_path"] == "/etc/x.ct-backup-TS"


def test_apply_verify_mismatch(monkeypatch):
    monkeypatch.setattr(ap, "_ssh", lambda a, c, t, input=None: FakeR(0))
    monkeypatch.setattr(ap, "read_file", lambda a, p, t: ("DIFFERENT\n", None))  # 적용 후 내용 다름
    res = ap.apply_intent("h", "/etc/x", "new\n", ap._sha("new\n"), ts="TS")
    assert res["ok"] is False and "verify" in res["error"]


def test_rollback(monkeypatch):
    cmds = []
    monkeypatch.setattr(ap, "_ssh", lambda a, c, t, input=None: cmds.append(c) or FakeR(0))
    res = ap.rollback("h", "/etc/x", "/etc/x.ct-backup-TS", sudo=False)
    assert res["ok"] is True
    assert cmds[0] == "cp -- /etc/x.ct-backup-TS /etc/x"
