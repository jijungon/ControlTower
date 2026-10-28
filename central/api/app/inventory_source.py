"""금고(OpenBao) 의 gw · 서버 목록을 읽는다 — 서버 탭의 '누가 · 어디로' 화면용.
(쓰기는 '목록 고치기'(CT_INVENTORY_EDIT, 기본 끔) 하나뿐 — 아래 read_entry · write_entry, 라우터는 routers/inventory_edit.py)

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
    """목록을 못 읽었다 — 화면에 '모름' 으로 보여 준다(빈 목록으로 보이지 않게).
    status = 금고가 답한 HTTP 코드. 답을 못 받았으면(시간 초과 · 끊김 · 답이 깨짐) None."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class InventoryConflict(InventoryError):
    """check-and-set 이 안 맞음 — 읽은 뒤 누가(idp-login 등) 먼저 고쳤다. 금고는 아무것도 안 썼다."""


class InventoryUnknown(InventoryError):
    """썼는지 모른다 — 답을 못 받았거나 5xx(앞단 LB 가 끊었어도 금고는 썼을 수 있음). '안 됨' 으로도 '됨' 으로도 보이지 않는다."""


_cache: dict = {"at": 0.0, "data": None}


def _addr() -> str:
    return (settings.ct_inventory_addr or os.getenv("CT_VAULT_ADDR") or "").rstrip("/")


def _why(exc: urllib.error.HTTPError) -> str:
    """금고가 적어 보낸 까닭(errors) — 'permission denied' · 'check-and-set …' 을 그대로 보이려고."""
    try:
        errs = json.loads(exc.read() or b"{}").get("errors") or []
    except Exception:  # noqa: BLE001 — 까닭을 못 읽어도 코드는 남는다
        return ""
    return (" — " + "; ".join(str(e) for e in errs))[:300] if errs else ""


def _call(method: str, path: str, token: str | None = None, body: dict | None = None, missing_ok: bool = True) -> dict:
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
        if exc.code == 404 and missing_ok:  # 그 환경에 목록이 아직 없다 — 빈 것으로
            return {}
        raise InventoryError(f"금고 {method} {path}: HTTP {exc.code}{_why(exc)}", status=exc.code) from exc
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


# ── 목록 고치기(운영자) — 한 항목씩, 캐시 없이 읽고 check-and-set 으로 쓴다 ──
# 금고에 하는 일은 이 둘뿐: GET  <mount>/data/<환경>/<서비스>          (읽기 — 판 번호 · 그 판의 시각도 같이 옴)
#                           POST <mount>/data/<환경>/<서비스>  {"options": {"cas": 읽은 판}, "data": 통째}
# → ct-inventory 정책에 필요한 것: inventory/data/* 의 read + update. create(새 서비스) · delete · metadata 쓰기는 안 쓴다.


def read_entry(env: str, service: str, token: str | None = None) -> dict | None:
    """한 항목을 그대로 — {"data", "version", "updated_at"}. 없으면(지워진 판 포함) None."""
    token = token or _login()
    d = _call("GET", f"{settings.ct_inventory_mount}/data/{env}/{service}", token).get("data") or {}
    if not isinstance(d.get("data"), dict):
        return None
    meta = d.get("metadata") or {}
    return {"data": d["data"], "version": meta.get("version"), "updated_at": meta.get("created_time")}


def write_entry(env: str, service: str, data: dict, cas: int, token: str | None = None) -> dict:
    """통째(data)를 cas=읽은 판 으로 쓴다 → {"version", "updated_at"}.
    그 사이 판이 바뀌었으면 InventoryConflict, 금고가 4xx 로 거절하면 InventoryError(둘 다 아무것도 안 씀),
    답을 못 받았거나 5xx 면 InventoryUnknown(썼을 수도 있음)."""
    token = token or _login()
    path = f"{settings.ct_inventory_mount}/data/{env}/{service}"
    try:
        resp = _call("POST", path, token, body={"options": {"cas": cas}, "data": data}, missing_ok=False)
    except InventoryError as exc:
        if exc.status == 400 and "check-and-set" in str(exc):
            raise InventoryConflict(str(exc), status=400) from exc
        if exc.status is not None and exc.status < 500:
            raise
        raise InventoryUnknown(str(exc), status=exc.status) from exc
    finally:
        clear_cache()  # 됐든 안 됐든 '누가 · 어디로' 는 다음에 금고에서 새로 읽는다
    out = resp.get("data") or {}
    if not isinstance(out.get("version"), int):
        raise InventoryUnknown(f"금고 POST {path}: 답에 새 판 번호가 없어요")
    return {"version": out["version"], "updated_at": out.get("created_time")}
