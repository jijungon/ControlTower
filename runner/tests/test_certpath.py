"""수집기 도장 길(#58) — 금고 도장으로 서버 정보 읽기. 실제 ssh · 금고 없이 subprocess · signer 를 가짜로.

지키는 것:
  - 서버에 실제로 가는 명령 글이 금고에 박힌 세 글과 **한 글자도** 같다(따옴표 · 공백 포함)
  - 거절(rc 126 + 'idp-collect:')은 오류도 정상도 아닌 '이 길로는 못 읽음'
  - 기본은 꺼짐(CT_CERT_SERVERS 빈 값) — 켜야만 로그인 · 접속
  - 대상은 금고 목록 이름으로만(목록에 없으면 추측 안 함), 키는 임시로 만들고 끝나면 지움
"""
import os
import subprocess
import types

import pytest

from runner import certpath, conn, signer
from runner.config import RunnerConfig

# 금고에 박힌 명령이 받아 주는 글 — 여기를 고치면 금고 쪽(IdP)도 같이 고쳐야 한다
APT = "apt list --upgradable"
YUM = "sh -lc 'command -v dnf >/dev/null 2>&1 && dnf -q check-update || yum -q check-update'"
REFUSE = "idp-collect: this certificate only runs: apt list --upgradable | dnf/yum check-update | cat -- /etc/... or compose file"
ADDR = "192.0.2.10"


def _prefix() -> list[str]:
    sess = certpath.CertSession.__new__(certpath.CertSession)  # 키를 만들지 않고 argv 모양만
    sess.key, sess.timeout = "/tmp/ct-cert-x/key", 8
    return sess.ssh_argv("/tmp/ct-cert-x/dev-cert.pub", ADDR)


@pytest.fixture
def ssh_calls(monkeypatch):
    """subprocess.run 대역 — 받은 argv 를 기록하고 정해 둔 답(rc, stdout, stderr)을 돌려준다."""
    calls: list[list[str]] = []
    answer = {"rc": 0, "out": "", "err": ""}

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, answer["rc"], answer["out"], answer["err"])

    monkeypatch.setattr(conn.subprocess, "run", fake_run)
    return types.SimpleNamespace(calls=calls, answer=answer)


def _remote(argv: list[str], prefix: list[str]) -> str:
    """ssh 가 서버로 보내는 한 줄 — 호스트 뒤 argv 를 공백으로 잇는다(ssh 가 하는 그대로)."""
    assert argv[: len(prefix)] == prefix and argv[len(prefix) - 1] == ADDR  # 앞부분 · 호스트를 실제로 확인한 뒤
    return " ".join(argv[len(prefix):])


# ── 박힌 명령 글자 일치 ──


def test_서버로_가는_명령_글이_박힌_세_글과_같다(ssh_calls):
    prefix = _prefix()
    ssh_calls.answer.update(rc=0, out="Listing...\n")
    conn.list_upgrades("x", 8, prefix)
    ssh_calls.answer.update(rc=100, out="")
    conn.list_upgrades_yum("x", 8, prefix)
    ssh_calls.answer.update(rc=0, out="127.0.0.1 localhost\n")
    conn.read_file("x", "/etc/hosts", 8, prefix)
    conn.read_file("x", "/app/shop/docker-compose.yml", 8, prefix)
    assert len(ssh_calls.calls) == 4  # 네 번 다 실제로 보냈나 먼저
    assert [_remote(a, prefix) for a in ssh_calls.calls] == [
        APT,
        YUM,
        "cat -- /etc/hosts",
        "cat -- /app/shop/docker-compose.yml",
    ]
    assert " ".join(conn.APT_UPGRADABLE) == APT and conn.YUM_CHECK_UPDATE == YUM


def test_key_모드도_같은_글을_보낸다(ssh_calls, monkeypatch):
    """~/.ssh/config 별칭으로 붙을 때(러너 CLI)도 같은 상수 — 한쪽만 바뀌지 않게."""
    monkeypatch.delenv("CT_SSH_MODE", raising=False)
    conn.list_upgrades("web-01")
    ssh_calls.answer.update(rc=100)
    conn.list_upgrades_yum("web-01")
    assert len(ssh_calls.calls) == 2
    tails = [" ".join(a[a.index("web-01") + 1:]) for a in ssh_calls.calls]
    assert tails == [APT, YUM]


def test_도장_길_ssh_앞부분(ssh_calls):
    p = _prefix()
    joined = " ".join(p)
    assert p[0] == "ssh" and p[-1] == ADDR
    assert "-F none" in joined  # 컨테이너 · PC 의 ssh 설정을 안 탐
    assert "-i /tmp/ct-cert-x/key" in joined and "CertificateFile=/tmp/ct-cert-x/dev-cert.pub" in joined
    assert "IdentitiesOnly=yes" in joined and "IdentityAgent=none" in joined  # 이 키 + 이 도장 하나로만
    assert "-l appuser" in joined and "BatchMode=yes" in joined


# ── 거절 구분 ──


def test_도장이_거절하면_이_길로는_못_읽음(ssh_calls):
    ssh_calls.answer.update(rc=126, err=REFUSE + "\n")
    content, err = conn.read_file("x", "/etc/hosts", 8, _prefix())
    assert ssh_calls.calls  # 실제로 보냈다
    assert content is None and err == conn.BLOCKED + REFUSE


@pytest.mark.parametrize("rc,err", [
    (126, "bash: /usr/bin/cat: Permission denied"),  # 126 이지만 금고 거절이 아님
    (1, REFUSE),                                     # 글은 있지만 126 이 아님
    (255, "ssh: connect to host 192.0.2.10 port 22: Connection refused"),
])
def test_둘_다일_때만_거절로_본다(ssh_calls, rc, err):
    ssh_calls.answer.update(rc=rc, err=err)
    _, why = conn.read_file("x", "/etc/hosts", 8, _prefix())
    assert ssh_calls.calls and why == err and not why.startswith(conn.BLOCKED)


def test_apt_가_없으면_dnf_yum_으로(ssh_calls, monkeypatch):
    answers = iter([(127, "", "sh: 1: exec: apt: not found"), (100, "bind.x86_64  32:9.11.4-26  updates\n", "")])

    def fake_run(argv, **kw):
        ssh_calls.calls.append(argv)
        rc, out, err = next(answers)
        return subprocess.CompletedProcess(argv, rc, out, err)

    monkeypatch.setattr(conn.subprocess, "run", fake_run)
    pkgs, err = conn.read_updates("x", 8, _prefix())
    assert len(ssh_calls.calls) == 2 and err is None
    assert pkgs == [{"name": "bind", "from": "", "to": "32:9.11.4-26", "security": False}]


# ── 박힌 cat 규칙 · 이름 ──


@pytest.mark.parametrize("path,ok", [
    ("/etc/hosts", True),
    ("/etc/nginx/conf.d/site.conf", True),
    ("/app/shop/docker-compose.yml", True),
    ("/app/shop/docker-compose.yaml", True),
    ("/app/shop/docker-compose.prod.yml", True),
    ("/srv/compose.yml", True),
    ("/srv/compose.yaml", True),
    ("/opt/app/app.conf", False),        # /etc 도 compose 도 아님
    ("/docker-compose.yml", False),       # 폴더 없이 맨 위
    ("/app/compose.yml.bak", False),
    ("/etc/../root/.ssh/id_rsa", False),  # '..'
    ("/etc/a b", False),                  # 공백 — 명령을 붙일 수 있음
    ("/etc/x;id", False),
    ("/etc/$(id)", False),
    ("etc/hosts", False),
])
def test_박힌_cat_규칙과_같은_선(path, ok):
    assert certpath.path_ok(path) is ok


def test_이름은_환경_서비스_서버_셋():
    good, bad = certpath.picks(" dev/shop/web-01, prod/shop/web-01 ,dev/shop/web-01, qa/shop/x, dev/shop, ,stg//x")
    assert good == ["dev/shop/web-01", "prod/shop/web-01"]
    assert bad == ["qa/shop/x", "dev/shop", "stg//x"]
    assert certpath.picks("") == ([], []) and certpath.picks(None) == ([], [])


# ── 기본은 꺼짐 ──


def test_기본은_꺼짐(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # .env 를 안 읽게
    monkeypatch.delenv("CT_CERT_SERVERS", raising=False)
    assert RunnerConfig.load().cert_servers == ""
    monkeypatch.setenv("CT_CERT_SERVERS", " dev/shop/web-01 ")
    assert RunnerConfig.load().cert_servers == "dev/shop/web-01"


class AgentAPI:
    """수집기(agent)가 부르는 중앙 API 대역 — 요청 하나를 주고 끝낸 결과를 기록."""

    def __init__(self, *a):
        self.finished = []

    def claim_collect(self, *a, **k):
        return {"id": 1}

    def finish_collect(self, rid, ok, message):
        AgentAPI.last = (ok, message)

    def close(self):
        pass


def _agent_cfg(**kw):
    return types.SimpleNamespace(central_url="x", api_token="t", runner_name="c", idp_status_file="", idp_people_file="",
                                 idp_access_file="", idp_gw_logins_file="", **kw)


def test_수집기는_꺼져_있으면_도장_길을_안_탄다(monkeypatch):
    import runner.cli as cli

    monkeypatch.setattr(cli, "CentralAPI", AgentAPI)
    monkeypatch.setattr(cli, "cmd_shape", lambda *a, **k: {"ok": True, "message": "서비스 3개"})
    touched = []
    monkeypatch.setattr(certpath, "collect", lambda *a, **k: touched.append(1) or {"ok": True, "message": "?"})
    monkeypatch.setattr(signer, "login", lambda: touched.append("login"))
    cli.cmd_agent(_agent_cfg(), once=True)  # cert_servers 없음(예전 설정)
    cli.cmd_agent(_agent_cfg(cert_servers=""), once=True)
    assert AgentAPI.last == (True, "서비스 3개") and touched == []


def test_수집기는_켜져_있으면_수집_뒤에_도장_길(monkeypatch):
    import runner.cli as cli

    monkeypatch.setattr(cli, "CentralAPI", AgentAPI)
    monkeypatch.setattr(cli, "cmd_shape", lambda *a, **k: {"ok": True, "message": "서비스 3개"})
    monkeypatch.setattr(certpath, "collect", lambda cfg, api: {"ok": False, "message": "도장 길: 금고 목록을 못 받음(off)"})
    cli.cmd_agent(_agent_cfg(cert_servers="dev/shop/web-01"), once=True)
    assert AgentAPI.last == (False, "서비스 3개 · 도장 길: 금고 목록을 못 받음(off)")  # 못 본 것을 '완료' 로 안 보임

    def boom(cfg, api):
        raise RuntimeError("뜻밖")
    monkeypatch.setattr(certpath, "collect", boom)
    cli.cmd_agent(_agent_cfg(cert_servers="dev/shop/web-01"), once=True)
    assert AgentAPI.last[0] is False and "도장 길 오류: RuntimeError: 뜻밖" in AgentAPI.last[1]


# ── 한 번 수집 (가짜 중앙 · 금고 · ssh) ──


class CollectAPI:
    def __init__(self, inventory=None, state="ok"):
        self.inventory = inventory if inventory is not None else [{"env": "dev", "service": "shop", "name": "web-01", "addr": ADDR}]
        self.state = state
        self.asked, self.imported, self.updates, self.confs = [], [], [], []

    def collect_servers(self, picks):
        self.asked.append(picks)
        return {"state": self.state, "servers": self.inventory, "missing": [], "error": "금고 HTTP 403"}

    def import_servers(self, servers):
        self.imported += servers
        return {"imported_new": len(servers), "total": len(servers)}

    def list_servers(self):
        return [{"hostname": "dev/shop/web-01", "id": 7}, {"hostname": "다른-서버", "id": 1}]

    def list_conf_targets(self):
        return ["/etc/hosts", "/opt/app/app.conf"]

    def upload_update_snapshots(self, snaps):
        self.updates += snaps

    def upload_conf_snapshots(self, snaps):
        self.confs += snaps


@pytest.fixture
def world(monkeypatch):
    """ssh-keygen · ssh · 금고 대역. ssh 가 불릴 때 도장 파일 내용도 기록(접속하는 순간 도장이 있었나)."""
    w = types.SimpleNamespace(keygen=[], ssh=[], certs=[], logins=0, signs=[], dirs=[])

    def fake_run(argv, **kw):
        if argv[0] == "ssh-keygen":
            key = argv[argv.index("-f") + 1]
            w.dirs.append(os.path.dirname(key))
            open(key, "w").write("PRIVATE")
            open(key + ".pub", "w").write("ssh-ed25519 AAAA ct-collector\n")
            w.keygen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        w.ssh.append(argv)
        cert = next(a.split("=", 1)[1] for a in argv if a.startswith("CertificateFile="))
        w.certs.append(open(cert).read())
        remote = " ".join(argv[argv.index(ADDR) + 1:])
        if remote == APT:
            return subprocess.CompletedProcess(argv, 0, "openssl/jammy-security 3.0.13 amd64 [upgradable from: 3.0.2]\n", "")
        if remote == "cat -- /etc/hosts":
            return subprocess.CompletedProcess(argv, 0, "127.0.0.1 localhost\n", "")
        return subprocess.CompletedProcess(argv, 126, "", REFUSE)

    def fake_login():
        w.logins += 1
        return "tok"

    def fake_sign(env, pub, token=None):
        w.signs.append((env, pub, token))
        return f"CERT-{env}"

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(signer, "login", fake_login)
    monkeypatch.setattr(signer, "sign", fake_sign)
    return w


def _cfg(servers="dev/shop/web-01"):
    return types.SimpleNamespace(cert_servers=servers, connect_timeout=8)


def test_한_번_수집(world):
    api = CollectAPI()
    res = certpath.collect(_cfg(), api)
    assert api.asked == [["dev/shop/web-01"]] and len(world.keygen) == 1  # 목록을 묻고 키를 실제로 만들었나 먼저
    # 금고: 로그인 한 번, 대상 서버의 환경(dev)으로 도장 한 번 — 새 키의 공개키로
    assert world.logins == 1 and world.signs == [("dev", "ssh-ed25519 AAAA ct-collector\n", "tok")]
    # 중앙 서버 목록에 금고 목록 이름으로 올림(주소는 목록 값 그대로, 계정 appuser)
    assert api.imported == [{"hostname": "dev/shop/web-01", "ip": ADDR, "ssh_user": "appuser", "ssh_port": 22}]
    # ssh 는 박힌 규칙 안의 것만: OS 패치 + /etc/hosts. /opt/app/app.conf 는 보내지 않음
    remotes = [" ".join(a[a.index(ADDR) + 1:]) for a in world.ssh]
    assert remotes == [APT, "cat -- /etc/hosts"] and world.certs == ["CERT-dev", "CERT-dev"]
    assert api.updates == [{"server_id": 7, "packages": [{"name": "openssl", "from": "3.0.2", "to": "3.0.13", "security": True}], "error": None}]
    by_path = {c["path"]: c for c in api.confs}
    assert by_path["/etc/hosts"] == {"server_id": 7, "path": "/etc/hosts", "content": "127.0.0.1 localhost\n", "error": None}
    assert by_path["/opt/app/app.conf"]["content"] is None and by_path["/opt/app/app.conf"]["error"].startswith(conn.BLOCKED)
    # 키 · 도장은 끝나면 지움
    assert world.dirs and not os.path.exists(world.dirs[0])
    assert res["ok"] is True and "1대" in res["message"] and "일부 이 길로는 못 읽음 1" in res["message"]


def test_금고가_거절한_경로는_못_읽음으로_올린다(world, monkeypatch):
    api = CollectAPI()
    monkeypatch.setattr(api, "list_conf_targets", lambda: ["/etc/shadow-like"])  # 규칙 안이지만 금고가 거절했다고 침
    certpath.collect(_cfg(), api)
    assert [" ".join(a[a.index(ADDR) + 1:]) for a in world.ssh][-1] == "cat -- /etc/shadow-like"
    assert api.confs == [{"server_id": 7, "path": "/etc/shadow-like", "content": None, "error": conn.BLOCKED + REFUSE}]


def test_목록에_없는_이름은_추측하지_않는다(world):
    api = CollectAPI(inventory=[])
    res = certpath.collect(_cfg("dev/shop/web-09"), api)
    assert api.asked == [["dev/shop/web-09"]]
    assert res["ok"] is False and "목록에 없음: dev/shop/web-09" in res["message"]
    assert world.logins == 0 and world.ssh == [] and world.keygen == [] and api.imported == []


@pytest.mark.parametrize("state", ["off", "error"])
def test_목록을_못_받으면_아무것도_안_한다(world, state):
    api = CollectAPI(state=state)
    res = certpath.collect(_cfg(), api)
    assert api.asked and res["ok"] is False and "금고 목록을 못 받음" in res["message"]
    assert world.logins == 0 and world.ssh == [] and api.updates == []


def test_도장을_못_받으면_서버마다_까닭을_올린다(world, monkeypatch):
    """못 읽은 것도 까닭과 함께 올린다 — 지난 값이 '정상' 으로 남아 보이지 않게."""
    def no_file():
        raise signer.SignerError("secret_id 파일이 없다: /secrets/secret_id")
    monkeypatch.setattr(signer, "login", no_file)
    api = CollectAPI()
    res = certpath.collect(_cfg(), api)
    assert world.keygen and world.ssh == []  # 키는 만들었고(시도함) 접속은 안 함
    want = "도장을 못 받음 — secret_id 파일이 없다: /secrets/secret_id"
    assert api.updates == [{"server_id": 7, "packages": None, "error": want}]
    assert [c["error"] for c in api.confs] == [want, want]
    assert res["ok"] is False and "secret_id 파일이 없다" in res["message"]
    assert not os.path.exists(world.dirs[0])


def test_목록의_주소가_이상하면_접속하지_않는다(world):
    api = CollectAPI(inventory=[{"env": "dev", "service": "shop", "name": "web-01", "addr": "-oProxyCommand=sh"}])
    certpath.collect(_cfg(), api)
    assert world.ssh == [] and api.updates[0]["error"] == "목록의 주소 모양이 이상해 접속하지 않음"


def test_plan_은_찾기까지만(world):
    api = CollectAPI()
    res = certpath.collect(_cfg(), api, plan=True)
    assert api.asked and res["ok"] is True and "찾음 1대" in res["message"]
    assert world.keygen == [] and world.logins == 0 and world.ssh == [] and api.imported == []
