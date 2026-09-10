"""SSH 접속 (asyncssh, nested) — **Phase 0 미사용**.

지금 접속 테스트는 conn.py(시스템 ssh + ~/.ssh/config)가 담당한다. 이 asyncssh 기반
프로그래매틱 nested-ssh 는 향후(수집기 병렬화 등)용으로 보존한다.

두 경로 지원.

  * direct       : 러너 로컬 키로 대상에 직접 접속
  * via_gateway  : gw 에 접속(로컬 gw 키) 후, gw 위에서 gw 가 보유한 키로
                   대상에 nested ssh. (대상 키는 각 gw 에 있고 러너 로컬엔 gw 키만
                   있다는 결정 반영 — PLAN 아키텍처)

동시성: gw별 세마포어로 상한(대규모·15 gw 대비). gw 에 세션이 몰리지 않게.

주의(TODO): known_hosts=None 은 호스트키 검증을 끈 상태다. 운영 전 known_hosts
관리로 교체할 것.
"""
from __future__ import annotations

import asyncio
import shlex
import time
from dataclasses import dataclass

import asyncssh

from .keystore import KeyStore


@dataclass
class Server:
    id: int
    hostname: str
    ssh_port: int
    ssh_user: str
    access_method: str                 # direct | via_gateway
    credential_alias: str | None
    gateway: "Server | None" = None


class SSHRunner:
    def __init__(self, keystore: KeyStore, connect_timeout: int = 10,
                 max_per_gateway: int = 5):
        self._ks = keystore
        self._timeout = connect_timeout
        self._max = max_per_gateway
        self._sem: dict[int, asyncio.Semaphore] = {}

    def _gate(self, gw_id: int) -> asyncio.Semaphore:
        if gw_id not in self._sem:
            self._sem[gw_id] = asyncio.Semaphore(self._max)
        return self._sem[gw_id]

    async def run(self, server: Server, command: str) -> tuple[bool, str, str]:
        """command 를 대상 서버에서 실행 -> (ok, stdout, stderr)."""
        try:
            if server.access_method == "direct":
                return await self._run_direct(server, command)
            return await self._run_via_gateway(server, command)
        except (asyncssh.Error, OSError, asyncio.TimeoutError) as e:
            return False, "", str(e)

    async def _run_direct(self, s: Server, command: str) -> tuple[bool, str, str]:
        cred = self._ks.resolve(s.credential_alias)
        async with asyncssh.connect(
            s.hostname, port=s.ssh_port, username=cred.username,
            client_keys=[cred.key_path], passphrase=cred.passphrase,
            known_hosts=None, connect_timeout=self._timeout,
        ) as conn:
            r = await conn.run(command, check=False)
            return (r.exit_status == 0, r.stdout or "", r.stderr or "")

    async def _run_via_gateway(self, s: Server, command: str) -> tuple[bool, str, str]:
        gw = s.gateway
        assert gw is not None, "via_gateway 인데 gateway 가 없음"
        gw_cred = self._ks.resolve(gw.credential_alias)
        async with self._gate(gw.id):
            # 1) 로컬 gw 키로 게이트웨이 접속
            async with asyncssh.connect(
                gw.hostname, port=gw.ssh_port, username=gw_cred.username,
                client_keys=[gw_cred.key_path], passphrase=gw_cred.passphrase,
                known_hosts=None, connect_timeout=self._timeout,
            ) as gw_conn:
                # 2) gw 위에서 gw 가 보유한 키로 대상에 nested ssh.
                #    (대상 개인키는 gw 의 ~/.ssh 등에 있다는 전제 — 러너 로컬엔 없음)
                remote = (
                    "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
                    f"-p {s.ssh_port} {shlex.quote(s.ssh_user + '@' + s.hostname)} "
                    f"{shlex.quote(command)}"
                )
                r = await gw_conn.run(remote, check=False)
                return (r.exit_status == 0, r.stdout or "", r.stderr or "")

    async def test_connection(self, server: Server) -> dict:
        """Phase 0 연결 테스트 — whoami 실행 + 지연 측정."""
        t0 = time.monotonic()
        ok, _out, err = await self.run(server, "whoami")
        latency = int((time.monotonic() - t0) * 1000)
        return {
            "server_id": server.id,
            "ok": ok,
            "latency_ms": latency,
            "error": None if ok else (err or "connect failed"),
        }
