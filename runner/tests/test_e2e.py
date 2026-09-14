"""러너 E2E — 실제 러너 CLI(import/test/conf)를 라이브 API + 가짜 ssh 로 태워 검증.

- 라이브 API: uvicorn 서브프로세스(임시 SQLite, 임의 포트)
- ssh: PATH 앞에 가짜 ssh 스텁 → conn.py 의 subprocess 를 실제로 실행(무해, SSH 서버 불필요)
- 러너 CLI 도 subprocess 로 실제 실행 → httpx → API → DB 까지 진짜 경로
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "central" / "api"
TOKEN = "e2e-token"

# 가짜 ssh: argv 에서 host/명령을 뽑아 FAKE_SSH_FIXTURES(json)의 응답을 흉내낸다.
FAKE_SSH = """#!/usr/bin/env python3
import os, sys, json
args = sys.argv[1:]
i, host, rest = 0, None, []
while i < len(args):
    a = args[i]
    if a == "-o":
        i += 2; continue
    if a.startswith("-"):
        i += 1; continue
    host = a; rest = args[i + 1:]; break
cmd = " ".join(rest)
fx = json.load(open(os.environ["FAKE_SSH_FIXTURES"]))
r = fx.get(host + "::" + cmd) or fx.get(host + "::*") or {"rc": 1, "stderr": "unknown host/cmd"}
sys.stdout.write(r.get("stdout", ""))
sys.stderr.write(r.get("stderr", ""))
sys.exit(r.get("rc", 0))
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    db = tmp_path_factory.mktemp("e2e-api") / "e2e.db"
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(API_DIR),
        "DATABASE_URL": f"sqlite:///{db}",
        "CT_API_TOKEN": TOKEN,
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(API_DIR), env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise RuntimeError("E2E API 서버가 뜨지 않음")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_runner(cmd, base, ssh_config, fixtures, fake_bin):
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(REPO),
        "CT_CENTRAL_URL": base,
        "CT_API_TOKEN": TOKEN,
        "CT_SSH_CONFIG": str(ssh_config),
        "FAKE_SSH_FIXTURES": str(fixtures),
    }
    return subprocess.run(
        [sys.executable, "-m", "runner.cli", *cmd],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=40,
    )


def test_runner_e2e(api, tmp_path):
    # 가짜 ssh 스텁
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh = fake_bin / "ssh"
    ssh.write_text(FAKE_SSH)
    ssh.chmod(0o755)

    # ssh config (import 대상)
    ssh_config = tmp_path / "sshconfig"
    ssh_config.write_text(
        "Host web-01\n  HostName 10.0.0.1\n  User deploy\n  IdentityFile ~/.ssh/k1\n"
        "Host web-02\n  HostName 10.0.0.2\n  User deploy\n"
    )

    path = "/etc/nginx/nginx.conf"
    fixtures = tmp_path / "fx.json"
    fixtures.write_text(json.dumps({
        "web-01::true": {"rc": 0},
        "web-02::true": {"rc": 255, "stderr": "ssh: connect to host 10.0.0.2: Connection refused"},
        f"web-01::cat -- {path}": {"rc": 0, "stdout": "gzip on;\nworker_processes 4;\n"},
        f"web-02::cat -- {path}": {"rc": 0, "stdout": "worker_processes 4;\n"},  # gzip 누락
        "web-01::apt list --upgradable": {
            "rc": 0,
            "stdout": "Listing...\n"
            "openssl/jammy-security 3.0.13 amd64 [upgradable from: 3.0.2]\n"
            "vim/jammy-updates 8.2.5 amd64 [upgradable from: 8.2.3]\n",
        },
        "web-02::apt list --upgradable": {"rc": 0, "stdout": "Listing...\n"},
        # 버전 프로브(web-01만 설치, web-02는 미매칭→rc1→건너뜀)
        "web-01::node --version": {"rc": 0, "stdout": "v20.11.1\n"},
        "web-01::npm --version": {"rc": 0, "stdout": "10.2.4\n"},
        "web-01::java -version": {"rc": 0, "stderr": 'openjdk version "17.0.9" 2023-10-17\n'},
        "web-01::python3 --version": {"rc": 0, "stdout": "Python 3.11.6\n"},
        "web-01::docker --version": {"rc": 0, "stdout": "Docker version 24.0.7, build afdd53b\n"},
    }))

    c = httpx.Client(base_url=api, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)

    # 1) import: ssh config → 인벤토리
    r = _run_runner(["import"], api, ssh_config, fixtures, fake_bin)
    assert r.returncode == 0, r.stderr
    assert {s["hostname"] for s in c.get("/api/servers").json()} == {"web-01", "web-02"}

    # 2) test: 연결 테스트 → 상태 갱신 (web-01 online, web-02 offline)
    r = _run_runner(["test"], api, ssh_config, fixtures, fake_bin)
    assert r.returncode == 0, r.stderr
    st = {s["hostname"]: s["status"] for s in c.get("/api/servers").json()}
    assert st["web-01"] == "online"
    assert st["web-02"] == "offline"

    # 3) conf: target 추가 → 수집 → 드리프트
    c.post("/api/conf/targets", json={"path": path})
    r = _run_runner(["conf"], api, ssh_config, fixtures, fake_bin)
    assert r.returncode == 0, r.stderr
    conf = {row["hostname"]: row["status"] for row in c.get("/api/conf").json()}
    assert conf == {"web-01": "no_baseline", "web-02": "no_baseline"}

    # web-01 을 기준본으로 채택 → web-01 synced, web-02 drift
    w1 = next(s["id"] for s in c.get("/api/servers").json() if s["hostname"] == "web-01")
    c.post("/api/conf/baselines/adopt", json={"path": path, "server_id": w1})
    conf = {row["hostname"]: row["status"] for row in c.get("/api/conf").json()}
    assert conf["web-01"] == "synced"
    assert conf["web-02"] == "drift"

    # 4) updates: apt 목록 수집 → 서버별 대기/보안 개수
    r = _run_runner(["updates"], api, ssh_config, fixtures, fake_bin)
    assert r.returncode == 0, r.stderr
    ups = {row["hostname"]: row for row in c.get("/api/updates").json()}
    assert ups["web-01"]["pending"] == 2
    assert ups["web-01"]["security"] == 1   # openssl(-security) 만 보안
    assert ups["web-02"]["pending"] == 0

    # 5) versions: 툴체인 버전 수집(web-01 설치, web-02 미설치→매트릭스 제외)
    r = _run_runner(["versions"], api, ssh_config, fixtures, fake_bin)
    assert r.returncode == 0, r.stderr
    vers = {row["hostname"]: row for row in c.get("/api/versions").json()}
    assert vers["web-01"]["tools"]["node"] == "20.11.1"
    assert vers["web-01"]["tools"]["java"] == "17.0.9"
    assert vers["web-01"]["tools"]["docker"] == "24.0.7"
    assert "web-02" not in vers

    # 6) 작업이력: 러너 액션이 감사 로그로 남는다
    actions = [a["action"] for a in c.get("/api/audit").json()]
    for expected in ("server.import", "conn.test", "conf.collect", "updates.collect", "versions.collect"):
        assert expected in actions, f"{expected} 누락: {actions}"
