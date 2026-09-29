"""비밀 어댑터 — 중앙 API 비밀(CT_API_TOKEN·CT_SECRET·DB_PASSWORD 등)의 출처를 갈아끼운다.

CT_SECRET_MODE:
  env  (기본) — 환경변수/.env 에서 (기존 동작). **아무것도 안 바뀜.**
  vault        — OpenBao KV 에서 읽어 환경변수로 주입(이미 설정된 값은 덮지 않음).
                 미설정·조회 실패면 조용히 env 로 폴백.

Settings() 생성 전에 hydrate_from_vault() 를 부른다(config.py). 중앙은 SSH 키 없이
좁게 스코프된 vault 토큰만 쥔다 — 키 파킹이 아니다.

환경변수(vault 모드):
  CT_VAULT_ADDR      OpenBao 주소 (예: https://bao.parameta.local)
  CT_VAULT_KV_PATH   KV 경로 (KV v2 면 <mount>/data/<name>)
  CT_VAULT_TOKEN     조회 토큰(좁은 read 권한)

TLS (CT_VAULT_ADDR 가 https:// 일 때만 적용 — http 면 아무 영향 없음):
  CT_VAULT_CACERT       OpenBao 서버 인증서를 발급한 CA 번들(PEM). 사내/사설 CA 면 필수.
  CT_VAULT_CLIENT_CERT  클라이언트 인증서(PEM) — OpenBao/LB 가 mTLS 를 요구할 때
  CT_VAULT_CLIENT_KEY   클라이언트 개인키(PEM)

운영 안전장치:
  CT_SECRET_REQUIRED  1/true → 조회 실패 시 폴백하지 않고 SecretSourceError 로 **기동을 막는다.**
                      운영에서는 반드시 켠다. 안 켜면 OpenBao 가 안 붙어도 앱이 그냥 떠서
                      ct_secret/ct_api_token 이 공개된 기본값(dev-*)으로 서비스될 수 있다.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request


class SecretSourceError(RuntimeError):
    """CT_SECRET_REQUIRED 가 켜진 상태에서 비밀을 못 가져왔을 때."""


def secret_mode() -> str:
    return (os.getenv("CT_SECRET_MODE") or "env").strip().lower() or "env"


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _fail(reason: str) -> None:
    """강제 모드면 기동 중단, 아니면 경고를 남기고 env 폴백."""
    if _truthy("CT_SECRET_REQUIRED"):
        raise SecretSourceError(f"CT_SECRET_REQUIRED=1 인데 비밀을 못 가져왔다: {reason}")
    print(f"[secret_source] {reason} → env 폴백", file=sys.stderr)


def hydrate_from_vault() -> None:
    """vault 모드면 OpenBao KV 를 읽어 os.environ 에 주입(setdefault). 그 외엔 아무것도 안 한다."""
    if secret_mode() != "vault":
        return
    addr = os.getenv("CT_VAULT_ADDR")
    path = os.getenv("CT_VAULT_KV_PATH")
    token = os.getenv("CT_VAULT_TOKEN")
    if not (addr and path and token):
        return _fail("CT_VAULT_ADDR/KV_PATH/TOKEN 미설정")
    data = _fetch_kv(addr, path, token)
    if not data:
        return _fail(f"KV 조회 실패·비어있음: {path} (TLS 는 CT_VAULT_CACERT/CLIENT_CERT 확인)")
    for key, value in data.items():
        os.environ.setdefault(key, str(value))  # 명시적으로 설정된 env 가 우선


def _ssl_context(addr: str) -> ssl.SSLContext | None:
    """https 일 때 쓸 SSL 컨텍스트(사설 CA + mTLS). http 면 None(기존 동작 그대로)."""
    if not addr.lower().startswith("https:"):
        return None
    ctx = ssl.create_default_context(cafile=os.getenv("CT_VAULT_CACERT") or None)
    client_cert = os.getenv("CT_VAULT_CLIENT_CERT")
    if client_cert:  # mTLS — 중앙이 자기 신분증을 제시
        ctx.load_cert_chain(client_cert, os.getenv("CT_VAULT_CLIENT_KEY") or None)
    return ctx


def _fetch_kv(addr: str, path: str, token: str) -> dict | None:
    """OpenBao KV 조회 → {키:값}. 실패 시 None. KV v2(data.data)·v1(data) 둘 다 처리."""
    url = f"{addr.rstrip('/')}/v1/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": token})
    try:
        # 컨텍스트 생성도 try 안에 — CA·키 파일 경로가 틀리면 여기서 터진다.
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context(addr)) as resp:
            body = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — 원인을 삼키지 않고 메시지로 남긴다
        print(f"[secret_source] OpenBao 조회 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]  # KV v2
    return data if isinstance(data, dict) else None  # KV v1
