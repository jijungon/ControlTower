"""금고(OpenBao) 의 gw · 서버 목록을 **읽기만** 한다 — 서버 탭의 '누가 · 어디로' 화면용.

목록은 idp-login(service add · server add · user add)이 금고 `inventory/<환경>/<서비스>` 에 적는다:
  {"gw": {"host", "port"}, "servers": {이름: 주소}, "users": {계정: {"email", "role", ...}}}

중앙은 서버 열쇠를 갖지 않는다. 여기서 쥐는 것은 **목록만 읽는** 기계 신분(AppRole ct-inventory)
하나다 — 도장(ssh-*/sign)은 못 찍는다. 목록 내용(주소)은 저장소·DB 에 두지 않고, 물을 때마다
금고에서 읽어 잠깐(기본 60초)만 기억한다.

CT_INVENTORY_MODE:
  off  (기본) — 아무것도 안 읽는다. 화면은 "금고에 연결 전" 을 보여 준다.
  vault        — AppRole 로 로그인해 목록을 읽는다.
환경변수(vault 모드): CT_INVENTORY_ADDR(비면 CT_VAULT_ADDR) · CT_INVENTORY_ROLE_ID(또는 _FILE) ·
  CT_INVENTORY_SECRET_ID_FILE(0600 파일 — 비밀을 환경변수에 두지 않는다) · TLS 는 CT_VAULT_CACERT 등 그대로.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .config import settings
from .secret_source import _ssl_context

ENVS = ("dev", "stg", "prod")


class InventoryError(RuntimeError):
    """목록을 못 읽었다 — 화면에 '모름' 으로 보여 준다(빈 목록으로 보이지 않게)."""


_cache: dict = {"at": 0.0, "data": None}


def _addr() -> str:
    return (settings.ct_inventory_addr or os.getenv("CT_VAULT_ADDR") or "").rstrip("/")


def _call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    addr = _addr()
    req = urllib.request.Request(
        f"{addr}/v1/{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Vault-Token": token} if token else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context(addr)) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # 그 환경에 목록이 아직 없다 — 빈 것으로
            return {}
        raise InventoryError(f"금고 {method} {path}: HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 — 원인을 삼키지 않고 화면에 남긴다
        raise InventoryError(f"금고 {method} {path}: {type(exc).__name__}: {exc}") from exc


def _login() -> str:
    role_id = settings.ct_inventory_role_id
    if not role_id and settings.ct_inventory_role_id_file:
        try:
            role_id = open(settings.ct_inventory_role_id_file).read().strip()
        except OSError as exc:
            raise InventoryError(f"role_id 파일을 못 읽는다: {settings.ct_inventory_role_id_file}") from exc
    sid_file = settings.ct_inventory_secret_id_file
    if not (_addr() and role_id and sid_file):
        raise InventoryError("CT_INVENTORY_ADDR(또는 CT_VAULT_ADDR) · ROLE_ID · SECRET_ID_FILE 가 비었다")
    try:
        secret_id = open(sid_file).read().strip()
    except OSError as exc:
        raise InventoryError(f"secret_id 파일을 못 읽는다: {sid_file}") from exc
    auth = _call("POST", "auth/approle/login", body={"role_id": role_id, "secret_id": secret_id}).get("auth") or {}
    if not auth.get("client_token"):
        raise InventoryError("AppRole 로그인 실패 — secret_id 만료가 가장 흔하다")
    return auth["client_token"]


def fetch_inventory() -> dict:
    """{환경: {서비스: 항목}} — 모든 환경. 거르는 것(누가 무엇을 보나)은 라우터가 한다."""
    if (settings.ct_inventory_mode or "off").strip().lower() != "vault":
        raise InventoryError("off")
    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < settings.ct_inventory_cache_seconds:
        return _cache["data"]
    token = _login()
    mount = settings.ct_inventory_mount
    out: dict[str, dict] = {}
    for env in ENVS:
        keys = (_call("LIST", f"{mount}/metadata/{env}", token).get("data") or {}).get("keys") or []
        out[env] = {}
        for k in keys:
            if k.endswith("/"):
                continue
            d = (_call("GET", f"{mount}/data/{env}/{k}", token).get("data") or {}).get("data") or {}
            out[env][k] = d
    _cache.update(at=now, data=out)
    return out


def clear_cache() -> None:
    _cache.update(at=0.0, data=None)
