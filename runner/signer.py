"""SSH 인증서 서명 — cert 모드에서 OpenBao SSH CA 로 단명 인증서를 받아온다.

OpenBao **HTTP API** 로 붙는다 (bao CLI 바이너리 불필요 — 중앙 secret_source 와 동일 방식).
기계신분(AppRole 또는 이미 발급된 토큰)으로 로그인 → ssh-client-signer/sign/<role> 서명 →
인증서 파일 경로를 돌려준다. 한 프로세스(=한 번의 수집 실행) 안에서는 1회만 서명하고 캐시한다.

**미설정(OpenBao 주소 없음)이면 None 을 돌려 key 모드로 폴백한다.**

환경변수:
  CT_BAO_ADDR            OpenBao 주소 (예: https://bao.parameta.local)   ← 없으면 비활성(None)
  CT_BAO_SSH_ROLE        서명 역할                                        [기본 runner-ro]
  CT_SSH_KEY             서명할 키의 개인키 경로(.pub 를 서명)             [기본 ~/.ssh/id_ed25519]
  CT_BAO_SSH_PRINCIPALS  인증서 principals (쉼표구분; 미설정이면 역할 default_user)
  CT_BAO_TOKEN           이미 발급된 토큰(있으면 AppRole 생략)
  CT_BAO_ROLE_ID / CT_BAO_SECRET_ID   AppRole 자격 (CT_BAO_TOKEN 없을 때)

TLS (CT_BAO_ADDR 가 https:// 일 때만 적용 — http 면 아무 영향 없음):
  CT_BAO_CACERT          OpenBao 서버 인증서를 발급한 CA 번들(PEM). 사내/사설 CA 면 필수.
                         미설정이면 OS 기본 신뢰 저장소.
  CT_BAO_CLIENT_CERT     클라이언트 인증서(PEM) — OpenBao/LB 가 mTLS 를 요구할 때
  CT_BAO_CLIENT_KEY      클라이언트 개인키(PEM). 인증서에 키가 같이 들어있으면 생략 가능.

운영 안전장치:
  CT_SSH_CERT_REQUIRED   1/true → 서명 실패 시 **key 로 조용히 폴백하지 않고** SignerError 로 중단.
                         운영에서는 반드시 켠다. 안 켜면 TLS·토큰 문제로 cert 모드가 무력화돼도
                         상주 키로 접속이 계속돼 문제를 눈치채지 못한다.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

# 한 프로세스 안의 인증서 캐시 (key_path, cert_path). 수집 1회 = 서명 1회.
_cache: tuple[str, str] | None = None
# 이미 낸 경고(서버 수만큼 반복 출력 방지).
_warned: set[str] = set()


class SignerError(RuntimeError):
    """CT_SSH_CERT_REQUIRED 가 켜진 상태에서 인증서를 못 받았을 때."""


def configured() -> bool:
    """cert 모드가 실제로 쓸 수 있게 설정됐는지(OpenBao 주소 유무)."""
    return bool(os.getenv("CT_BAO_ADDR"))


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _key_path() -> str:
    return os.path.expanduser(os.getenv("CT_SSH_KEY", "~/.ssh/id_ed25519"))


def reset_cache() -> None:
    """테스트·재실행용: 프로세스 캐시를 비운다."""
    global _cache
    _cache = None
    _warned.clear()


def _warn(msg: str) -> None:
    """같은 메시지는 한 번만 — ssh_access_opts 는 서버마다 불린다."""
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"[signer] {msg}", file=sys.stderr)


def _fail(reason: str) -> None:
    """cert 모드 실패 처리 — 강제 모드면 중단, 아니면 경고를 남기고 key 폴백(None)."""
    if _truthy("CT_SSH_CERT_REQUIRED"):
        raise SignerError(f"CT_SSH_CERT_REQUIRED=1 인데 인증서를 못 받았다: {reason}")
    _warn(f"{reason} → key 모드로 폴백")
    return None


def ensure_cert(alias: str) -> tuple[str, str] | None:
    """(key_path, cert_path) 를 돌려준다. 미설정·실패면 None(→ 호출측이 key 폴백).

    alias 는 지금은 쓰지 않는다(runner-ro 단일 역할). 나중에 환경별 역할 분기에 사용 가능.
    """
    global _cache
    if not configured():
        return _fail("CT_BAO_ADDR 미설정 — cert 모드를 쓸 수 없다")
    if _cache is not None:
        return _cache
    key = _key_path()
    pub = key + ".pub"
    if not Path(pub).exists():
        return _fail(f"서명할 공개키가 없다: {pub}")
    cert = _sign(Path(pub).read_text(), key)
    if cert is None:
        return _fail("OpenBao 서명 실패 — 주소·토큰·TLS(CT_BAO_CACERT/CLIENT_CERT) 확인")
    _cache = (key, cert)
    return _cache


def _ssl_context() -> ssl.SSLContext | None:
    """https 일 때 쓸 SSL 컨텍스트(사설 CA + mTLS). http 면 None(기존 동작 그대로).

    urlopen(context=None) 은 기본 컨텍스트와 같으므로 http/미설정 경로는 전혀 안 바뀐다.
    """
    if not (os.getenv("CT_BAO_ADDR") or "").lower().startswith("https:"):
        return None
    ctx = ssl.create_default_context(cafile=os.getenv("CT_BAO_CACERT") or None)
    client_cert = os.getenv("CT_BAO_CLIENT_CERT")
    if client_cert:  # mTLS — 러너가 자기 신분증을 제시
        ctx.load_cert_chain(client_cert, os.getenv("CT_BAO_CLIENT_KEY") or None)
    return ctx


def _post(path: str, token: str | None, payload: dict) -> dict | None:
    """OpenBao HTTP POST → 응답 JSON(dict). 실패 시 경고를 남기고 None."""
    addr = os.environ["CT_BAO_ADDR"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    req = urllib.request.Request(
        f"{addr}/v1/{path}", data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        # 컨텍스트 생성도 try 안에 — CA·키 파일 경로가 틀리면 여기서 터진다.
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — 원인을 삼키지 않고 메시지로 남긴다
        _warn(f"OpenBao 요청 실패 ({path}): {type(exc).__name__}: {exc}")
        return None


def _token() -> str | None:
    """직접 토큰(CT_BAO_TOKEN) 우선, 없으면 AppRole 로그인. 실패 시 None."""
    tok = os.getenv("CT_BAO_TOKEN")
    if tok:
        return tok
    role_id, secret_id = os.getenv("CT_BAO_ROLE_ID"), os.getenv("CT_BAO_SECRET_ID")
    if not (role_id and secret_id):
        return None
    body = _post("auth/approle/login", None, {"role_id": role_id, "secret_id": secret_id})
    return (body or {}).get("auth", {}).get("client_token")


def _sign(public_key: str, key_path: str) -> str | None:
    """OpenBao 로 공개키를 서명 → 인증서 파일(<key>-cert.pub) 경로. 실패 시 None."""
    token = _token()
    if token is None:
        return None
    role = os.getenv("CT_BAO_SSH_ROLE", "runner-ro")
    payload = {"public_key": public_key}
    principals = os.getenv("CT_BAO_SSH_PRINCIPALS")
    if principals:
        payload["valid_principals"] = principals
    body = _post(f"ssh-client-signer/sign/{role}", token, payload)
    signed = (body or {}).get("data", {}).get("signed_key")
    if not signed:
        return None
    cert_path = key_path + "-cert.pub"
    Path(cert_path).write_text(signed)
    return cert_path
