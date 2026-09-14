"""접속 점검(probe) — 키 단독 접속 가능? 추가 인증(2FA) 필요? (읽기 전용).

ssh -v 로 접속을 시도(BatchMode: 대화형 프롬프트 없음)하고 로그 신호로 분류한다.
2FA 감지는 휴리스틱: 'partial success'(키는 통과, 2차 요구) 또는 keyboard-interactive 거부.
"""
from __future__ import annotations

import subprocess

_NET = (
    "connection refused",
    "connection timed out",
    "operation timed out",
    "timed out",
    "no route to host",
    "could not resolve",
    "network is unreachable",
)


def classify(rc: int, stderr: str) -> dict:
    """(ok, needs_2fa, detail) 판정. ok=키 단독 접속 성공(rc0)."""
    s = (stderr or "").lower()
    if rc == 0:
        return {"ok": True, "needs_2fa": False, "detail": "키 단독 접속 OK"}
    if "partial success" in s:
        return {"ok": False, "needs_2fa": True, "detail": "키 통과 후 추가 인증 필요(2FA 추정)"}
    if "permission denied" in s and "keyboard-interactive" in s:
        return {"ok": False, "needs_2fa": True, "detail": "추가 인증 필요(keyboard-interactive)"}
    if any(n in s for n in _NET):
        return {"ok": False, "needs_2fa": False, "detail": "네트워크 접속 불가"}
    if "host key verification failed" in s:
        return {"ok": False, "needs_2fa": False, "detail": "호스트키 검증 실패"}
    if "permission denied" in s:
        return {"ok": False, "needs_2fa": False, "detail": "키 거부(접속 권한 없음)"}
    return {"ok": False, "needs_2fa": False, "detail": "접속 실패"}


def probe_ssh(alias: str, timeout: int = 8) -> dict:
    """서버에 키로 접속 점검. {ok, needs_2fa, detail} 반환. 서버 변경 없음(true 만 실행)."""
    try:
        r = subprocess.run(
            [
                "ssh", "-v",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={timeout}",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "PreferredAuthentications=publickey,keyboard-interactive",
                "-o", "NumberOfPasswordPrompts=0",
                alias, "true",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        return classify(r.returncode, r.stderr)
    except subprocess.TimeoutExpired:
        return {"ok": False, "needs_2fa": False, "detail": "timeout"}
    except FileNotFoundError:
        return {"ok": False, "needs_2fa": False, "detail": "ssh not found"}
