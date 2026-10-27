"""GET /api/access — 서버 탭 '누가 · 어디로' (보기 전용).

왼쪽(사람): Gmail 마다 운영자 · 개발자, 그리고 들어가는 계정 — 운영자는 gw · 서버 모두 ubuntu,
           개발자는 gw 에 개인 계정 · 서버에 appuser.
오른쪽(곳): 환경 → gw → 서버, 그리고 칠 명령.

누가 무엇을 보나 — Authentik 그룹으로 거른다 (금고 정책과 같은 선):
  server-admin → dev · stg · prod 전부 / developer → dev · stg 만 / 둘 다 아니면 아무것도.
  로그인 없는 모드(CT_AUTH_MODE=none, 로컬 개발)는 전부.
운영자 이름은 아직 금고에 없다(Authentik 그룹이 원본) — "server-admin 그룹 전원" 한 줄로 보인다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Principal, auth_mode, current_user
from ..inventory_source import ENVS, InventoryError, fetch_inventory

router = APIRouter(prefix="/api", tags=["access"])

AUDIENCE = {"dev": "개발자 · 운영자", "stg": "개발자 · 운영자", "prod": "운영자만"}


def _scope(user: Principal) -> tuple[list[str], str]:
    if auth_mode() != "oidc":
        return list(ENVS), "로그인 없음(로컬)"
    if "server-admin" in user.groups:
        return list(ENVS), "운영자"
    if "developer" in user.groups:
        return ["dev", "stg"], "개발자"
    return [], "권한 없음"


def _user_row(acct: str, x) -> dict:
    if isinstance(x, str):  # 예전 모양 — 이메일만
        x = {"email": x}
    return {
        "email": x.get("email") or "",
        "role": "developer",
        "gw_account": x.get("gw_account") or acct,
        "server_account": x.get("server_account") or "appuser",
    }


@router.get("/access")
def access(user: Principal = Depends(current_user)) -> dict:
    envs, viewer_role = _scope(user)
    base = {"viewer": {"email": user.email, "role": viewer_role}, "envs": [], "people": []}
    if not envs:
        return {**base, "state": "denied"}
    try:
        inv = fetch_inventory()
    except InventoryError as exc:
        if str(exc) == "off":
            return {**base, "state": "off"}
        return {**base, "state": "error", "error": str(exc)}

    people: dict[str, dict] = {}
    out_envs = []
    for env in envs:
        services = []
        for name, v in sorted((inv.get(env) or {}).items()):
            users = [_user_row(a, x) for a, x in sorted((v.get("users") or {}).items())]
            for u in users:
                p = people.setdefault(u["email"], {**u, "where": []})
                p["where"].append({"env": env, "service": name})
            gw = v.get("gw") or {}
            services.append({
                "name": name,
                "gw": {"host": gw.get("host"), "port": gw.get("port", 22)} if gw.get("host") else None,
                "servers": [{"name": n, "addr": a} for n, a in sorted((v.get("servers") or {}).items())],
                "developers": [u["email"] for u in users],
            })
        out_envs.append({"env": env, "audience": AUDIENCE[env], "services": services})

    admins = {
        "email": "server-admin 그룹 전원",
        "role": "admin",
        "gw_account": "ubuntu",
        "server_account": "ubuntu",
        "note": "appuser 는 sudo -iu appuser",
        "where": [{"env": e["env"], "service": s["name"]} for e in out_envs for s in e["services"]],
    }
    rows = [admins] + sorted(people.values(), key=lambda p: p["email"])
    return {**base, "state": "ok", "envs": out_envs, "people": rows}
