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
