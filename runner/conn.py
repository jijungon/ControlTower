"""접속 테스트 — 시스템 ssh 로 ~/.ssh/config 를 그대로 활용(ProxyJump·IdentityFile 포함).

별도 키스토어 없이, 사용자의 기존 ssh 설정으로 접속되는지만 확인한다.
"""
from __future__ import annotations

import shlex
import subprocess

from .access import ssh_access_opts


def _ssh_argv(alias: str, timeout: int) -> list[str]:
    """모든 조회가 공유하는 ssh 프리픽스. 접속 수단(key/cert)은 access 어댑터가 결정한다."""
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        "-o", "StrictHostKeyChecking=accept-new",
        *ssh_access_opts(alias),
        alias,
    ]


def test_ssh(alias: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                "true",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 6,
        )
        if r.returncode == 0:
            return True, ""
        err = r.stderr.strip()
        return False, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "ssh not found"


def read_file(alias: str, path: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """서버의 파일 내용을 읽는다(시스템 ssh cat). (content, error) — 실패 시 (None, error)."""
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                "cat", "--", path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if r.returncode == 0:
            return r.stdout, None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def parse_ssh_aliases(text: str) -> dict[str, str]:
    """ssh 설정 글 → {HostName(주소): Host 이름}. 와일드카드(*, ?) Host 는 뺌, 같은 주소면 먼저 나온 이름."""
    out: dict[str, str] = {}
    names: list[str] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key, val = parts[0].lower(), parts[1].strip()
        if key == "host":
            names = [n for n in val.split() if not any(c in n for c in "*?!")]
        elif key == "hostname" and names:
            out.setdefault(val, names[0])
    return out


def gateway_aliases(gateway: str, timeout: int = 8) -> dict[str, str]:
    """게이트웨이 로그인 계정의 ~/.ssh/config 를 읽어 {주소: 이름}. 읽기만 한다(cat). 못 읽으면 {}.

    gw 에 이름으로 등록된 서버는 그 이름으로 들어가야 gw 가 맞춰 둔 계정·키·지문(known_hosts)을 그대로 쓴다.
    """
    try:
        r = subprocess.run([*_ssh_argv(gateway, timeout), "cat ~/.ssh/config"], capture_output=True, text=True, timeout=timeout + 15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    return parse_ssh_aliases(r.stdout) if r.returncode == 0 else {}


def read_file_via(gateway: str, target: str, path: str, timeout: int = 8, user: str | None = None) -> tuple[str | None, str | None]:
    """게이트웨이를 거쳐 안쪽 서버의 파일을 읽는다: PC → gateway(~/.ssh/config 별칭) → gw 위에서 ssh target cat.

    안쪽 접속은 gw 자신의 ssh 설정·키를 그대로 쓴다(ControlTower 원래 설계: 서버 키는 gw 에).
    BatchMode·ConnectTimeout 만 주고 호스트 키 정책은 gw 설정을 따른다 — gw 의 known_hosts 를 새로 쓰지 않게.
    읽기만 한다(cat). (content, error).
    """
    dest = f"{user}@{target}" if user else target
    inner = " ".join(
        shlex.quote(a)
        for a in ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", dest, "cat", "--", path]
    )
    try:
        r = subprocess.run(
            [*_ssh_argv(gateway, timeout), inner],
            capture_output=True,
            text=True,
            timeout=timeout * 2 + 15,
        )
        if r.returncode == 0:
            return r.stdout, None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def run_remote(alias: str, command: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """원격 명령을 실행하고 출력을 읽는다(조회 용도). (stdout+stderr, error).

    버전 프로브(`node --version`, `java -version` 등)에 사용 — 서버를 변경하지 않는다.
    버전은 stdout/stderr 어느 쪽이든 나올 수 있어 둘을 합쳐 돌려준다.
    """
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if r.returncode == 0:
            return (r.stdout or "") + (r.stderr or ""), None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def list_upgrades_yum(alias: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """yum/dnf 업그레이드 목록(조회만). rc 100=업데이트 있음(정상), 0=없음. dnf 우선, 없으면 yum."""
    cmd = "sh -lc 'command -v dnf >/dev/null 2>&1 && dnf -q check-update || yum -q check-update'"
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                cmd,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )
        if r.returncode in (0, 100):   # yum/dnf: 100 = 업데이트 있음
            return r.stdout, None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def list_upgrades(alias: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """대기 중인 apt 업그레이드 목록을 읽는다(`apt list --upgradable`). (stdout, error).

    읽기 전용 조회다 — 서버를 변경하지 않는다(설치·업그레이드 안 함).
    apt 는 stderr 로 "unstable CLI" 경고를 내지만 rc 0·stdout 목록은 유효하다.
    """
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                "apt", "list", "--upgradable",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )
        if r.returncode == 0:
            return r.stdout, None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"
