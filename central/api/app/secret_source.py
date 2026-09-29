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
"""
from __future__ import annotations

import json
import os
import urllib.request


def secret_mode() -> str:
    return (os.getenv("CT_SECRET_MODE") or "env").strip().lower() or "env"


def hydrate_from_vault() -> None:
    """vault 모드면 OpenBao KV 를 읽어 os.environ 에 주입(setdefault). 그 외엔 아무것도 안 한다."""
    if secret_mode() != "vault":
        return
    addr = os.getenv("CT_VAULT_ADDR")
    path = os.getenv("CT_VAULT_KV_PATH")
    token = os.getenv("CT_VAULT_TOKEN")
    if not (addr and path and token):
        return  # 미설정 → env 폴백
    data = _fetch_kv(addr, path, token)
    for key, value in (data or {}).items():
        os.environ.setdefault(key, str(value))  # 명시적으로 설정된 env 가 우선


def _fetch_kv(addr: str, path: str, token: str) -> dict | None:
    """OpenBao KV 조회 → {키:값}. 실패 시 None. KV v2(data.data)·v1(data) 둘 다 처리."""
    url = f"{addr.rstrip('/')}/v1/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
    except Exception:
        return None
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]  # KV v2
    return data if isinstance(data, dict) else None  # KV v1
