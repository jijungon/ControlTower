"""접속 어댑터 — 러너가 서버에 붙는 '수단'을 갈아끼운다 (IdP-옵셔널).

CT_SSH_MODE 환경변수로 선택:
  key  (기본) — 기존 방식. ~/.ssh/config 의 IdentityFile(상주 키)로 접속. **동작 안 바뀜.**
  cert         — OpenBao SSH CA 가 서명한 단명 인증서로 접속
                 (ssh -i <key> -o CertificateFile=<cert>). 서명은 runner.signer 가 담당(OpenBao 필요).
                 서명 실패·미설정이면 key 로 자동 폴백(안전).

기본이 key 라 플랫폼(IdP) 없이도 그대로 돈다. 플랫폼이 서면 CT_SSH_MODE=cert 로 스위치만 하면 된다.
"""
from __future__ import annotations

import os


def ssh_mode() -> str:
    """현재 접속 모드('key' 또는 'cert'). 미설정·빈값은 'key'."""
    return (os.getenv("CT_SSH_MODE") or "key").strip().lower() or "key"


def ssh_access_opts(alias: str) -> list[str]:
    """접속 모드에 따라 ssh argv 에 끼울 옵션 조각.

    key/미설정 → [] (기존 ~/.ssh/config 그대로).
    cert       → ['-i', <key>, '-o', 'CertificateFile=<cert>'] (서명 성공 시). 실패하면 [] 로 폴백.
    """
    if ssh_mode() != "cert":
        return []
    from . import signer  # 지연 임포트: key 모드에선 signer 를 아예 건드리지 않음

    got = signer.ensure_cert(alias)
    if not got:
        return []  # 서명 실패·미설정 → key 폴백(상주 키가 있으면 계속 동작)
    key_path, cert_path = got
    return ["-i", key_path, "-o", f"CertificateFile={cert_path}"]
