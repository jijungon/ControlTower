"""접속 테스트 — 시스템 ssh 로 ~/.ssh/config 를 그대로 활용(ProxyJump·IdentityFile 포함).

별도 키스토어 없이, 사용자의 기존 ssh 설정으로 접속되는지만 확인한다.
"""
from __future__ import annotations

import subprocess


def test_ssh(alias: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                alias,
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
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                alias,
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


def run_remote(alias: str, command: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """원격 명령을 실행하고 출력을 읽는다(조회 용도). (stdout+stderr, error).

    버전 프로브(`node --version`, `java -version` 등)에 사용 — 서버를 변경하지 않는다.
    버전은 stdout/stderr 어느 쪽이든 나올 수 있어 둘을 합쳐 돌려준다.
    """
    try:
        r = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                alias,
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
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                alias,
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
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                alias,
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
