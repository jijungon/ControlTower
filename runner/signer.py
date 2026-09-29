"""SSH 인증서 서명 — cert 모드에서 OpenBao SSH CA 로 단명 인증서를 받아온다.

기계신분(AppRole 또는 이미 발급된 토큰)으로 OpenBao 에 로그인 → ssh-client-signer/sign/<role>
로 공개키를 서명 → 인증서 파일 경로를 돌려준다. 한 프로세스(=한 번의 수집 실행) 안에서는
1회만 서명하고 캐시한다(서버마다 다시 서명하지 않는다 — 인증서는 principal 기반이라 공용).

**미설정(OpenBao 주소 없음)이면 None 을 돌려 key 모드로 폴백한다.**

환경변수:
  CT_BAO_ADDR      OpenBao 주소 (예: https://bao.parameta.local)   ← 없으면 비활성(None)
  CT_BAO_SSH_ROLE  서명 역할                                        [기본 runner-ro]
  CT_SSH_KEY       서명할 키의 개인키 경로(.pub 를 서명)             [기본 ~/.ssh/id_ed25519]
  CT_BAO_TOKEN     이미 발급된 토큰(있으면 AppRole 생략)
  CT_BAO_ROLE_ID / CT_BAO_SECRET_ID   AppRole 자격 (CT_BAO_TOKEN 없을 때)
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# 한 프로세스 안의 인증서 캐시 (key_path, cert_path). 수집 1회 = 서명 1회.
_cache: tuple[str, str] | None = None


def configured() -> bool:
    """cert 모드가 실제로 쓸 수 있게 설정됐는지(OpenBao 주소 유무)."""
    return bool(os.getenv("CT_BAO_ADDR"))


def _key_path() -> str:
    return os.path.expanduser(os.getenv("CT_SSH_KEY", "~/.ssh/id_ed25519"))


def reset_cache() -> None:
    """테스트·재실행용: 프로세스 캐시를 비운다."""
    global _cache
    _cache = None


def ensure_cert(alias: str) -> tuple[str, str] | None:
    """(key_path, cert_path) 를 돌려준다. 미설정·실패면 None(→ 호출측이 key 폴백).

    alias 는 지금은 쓰지 않는다(runner-ro 단일 역할). 나중에 환경별 역할 분기에 사용 가능.
    """
    global _cache
    if not configured():
        return None
    if _cache is not None:
        return _cache
    key = _key_path()
    pub = key + ".pub"
    if not Path(pub).exists():
        return None
    cert = _sign(pub, key)
    if cert is None:
        return None
    _cache = (key, cert)
    return _cache


def _bao_token(env: dict[str, str]) -> str | None:
    """직접 토큰(CT_BAO_TOKEN) 우선, 없으면 AppRole 로그인. 실패 시 None."""
    tok = os.getenv("CT_BAO_TOKEN")
    if tok:
        return tok
    role_id, secret_id = os.getenv("CT_BAO_ROLE_ID"), os.getenv("CT_BAO_SECRET_ID")
    if not (role_id and secret_id):
        return None
    r = subprocess.run(
        ["bao", "write", "-field=token", "auth/approle/login",
         f"role_id={role_id}", f"secret_id={secret_id}"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def _sign(pub_path: str, key_path: str) -> str | None:
    """OpenBao 로 공개키를 서명 → 인증서 파일(<key>-cert.pub) 경로. 실패 시 None."""
    env = dict(os.environ, BAO_ADDR=os.environ["CT_BAO_ADDR"])
    token = _bao_token(env)
    if token is None:
        return None
    env["BAO_TOKEN"] = token
    role = os.getenv("CT_BAO_SSH_ROLE", "runner-ro")
    try:
        r = subprocess.run(
            ["bao", "write", "-field=signed_key",
             f"ssh-client-signer/sign/{role}", f"public_key=@{pub_path}"],
            env=env, capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    cert_path = key_path + "-cert.pub"
    Path(cert_path).write_text(r.stdout)
    return cert_path
