"""GET /api/access — 서버 탭 '누가 · 어디로' (보기 전용).

왼쪽(사람): Gmail 마다 운영자 · 개발자, 그리고 들어가는 계정 — 운영자는 gw · 서버 모두 ubuntu,
           개발자는 gw 에 개인 계정 · 서버에 appuser.
오른쪽(곳): 환경 → gw → 서버, 그리고 칠 명령.

누가 무엇을 보나 — Authentik 그룹으로 거른다 (금고 정책과 같은 선):
  server-admin → dev · stg · prod 전부 / developer → dev · stg 만 / 둘 다 아니면 아무것도.
  그룹을 모르면(CT_AUTH_MODE=none, 또는 proxy 인데 서명 맞는 토큰이 없음) 막는다 — '모른다' 를 '다 볼 수 있다' 로 보지 않는다.
    운영은 앞단 Authentik 만 로그인하고 ControlTower 는 사용자를 모른다 → 그대로 '전부' 를 주면
    developer · viewer 에게도 운영(prod) gw · 서버 주소가 간다. 로컬 미리보기만 CT_ACCESS_LOCAL_PREVIEW=1 로 연다.
  금고 연결이 꺼져 있으면(off) 사용자와 상관없이 '연결 전' — 금고는 읽지도 않는다.
이름은 사람 이름표(routers/idp_people.py — Authentik 의 server-admin · developer 목록)에서 붙인다. 키는 이메일(소문자).
  운영자 줄: 이름표가 ok 면 server-admin 사람들(활성 먼저, 비활성은 active=false) — 운영자 줄은 그대로 하나(선도 하나).
  이름표를 모르면(연결 전 · 못 읽음 · 멈춤) "server-admin 그룹 전원" 그대로 + '이름 모름' — '운영자 없음' 으로 보이지 않게.
  개발자 줄: 이름표에서 찾으면 name · active, 못 찾으면 None(이메일만).
can_edit = 화면에 '고치기' 를 보일까(CT_INVENTORY_EDIT 가 켜졌고 운영자일 때만) — 고치기 자체는 routers/inventory_edit.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import Principal, auth_mode, current_user
from ..config import settings
from ..db import get_db
from ..inventory_source import ENVS, InventoryError, fetch_inventory
from . import idp_people
from .inventory_edit import can_edit

router = APIRouter(prefix="/api", tags=["access"])

AUDIENCE = {"dev": "개발자 · 운영자", "stg": "개발자 · 운영자", "prod": "운영자만"}


def _inventory_on() -> bool:
    return (settings.ct_inventory_mode or "off").strip().lower() == "vault"


def _scope(user: Principal) -> tuple[list[str] | None, str]:
    """(볼 수 있는 환경, 보는 사람 역할). 환경이 None 이면 '누군지 모름' — 막는다."""
    if auth_mode() not in ("oidc", "proxy"):
        if settings.ct_access_local_preview:
            return list(ENVS), "로그인 없음(로컬 미리보기)"
        return None, "모름"
    if not user.authenticated:  # proxy 인데 토큰이 없거나 틀림 — 그룹 없음(권한 없음)이 아니라 모름
        return None, "모름"
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


def _named(row: dict, known: dict[str, dict]) -> dict:
    """개발자 줄에 이름표 이름 — 금고의 이메일을 소문자로 찾는다. 못 찾으면(이름표를 모를 때도) name · active 가 None."""
    p = known.get(row["email"].strip().lower())
    return {**row, "name": idp_people.shown_name(p) if p else None, "active": p.get("active") if p else None}


def _admins(names: dict) -> tuple[list[dict], str | None]:
    """운영자 줄에 넣을 사람들(활성 먼저) + 짧은 알림. 이름표를 모르면 사람 없이 '이름 모름' — '운영자 없음' 이 아니다."""
    if names["state"] != "ok":
        why = "이름표 연결 전" if names["state"] == "off" else "이름표를 못 읽음"
        return [], f"이름 모름({why})"
    members = [
        {"name": idp_people.shown_name(p), "email": p.get("email"), "active": p.get("active") is not False}
        for p in names["people"] if "server-admin" in (p.get("groups") or [])
    ]
    members.sort(key=lambda m: not m["active"])  # 활성 먼저 — 나머지 순서는 파일 그대로(이메일 순)
    expected = (names.get("groups") or {}).get("server-admin")
    if not members:
        return [], "이름 모름(이름표에서 server-admin 사람을 못 찾음)"
    if expected is not None and expected != len(members):
        return members, f"이름표 머리에는 운영자 {expected}명인데 {len(members)}명만 읽었어요"
    return members, None


@router.get("/access")
def access(user: Principal = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    envs, viewer_role = _scope(user)
    base = {"viewer": {"email": user.email, "role": viewer_role}, "envs": [], "people": []}
    if not _inventory_on():
        return {**base, "state": "off"}
    if envs is None:  # 그룹을 모름 → 금고를 읽지도 않고 막는다
        return {**base, "state": "no_identity"}
    if not envs:
        return {**base, "state": "denied"}
    try:
        inv = fetch_inventory()
    except InventoryError as exc:
        if str(exc) == "off":
            return {**base, "state": "off"}
        return {**base, "state": "error", "error": str(exc)}

    names = idp_people.current(db)
    known = idp_people.by_email(names)
    people: dict[str, dict] = {}
    out_envs = []
    for env in envs:
        services = []
        for name, v in sorted((inv.get(env) or {}).items()):
            users = [_named(_user_row(a, x), known) for a, x in sorted((v.get("users") or {}).items())]
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

    members, names_note = _admins(names)
    admins = {
        "email": "server-admin 그룹 전원",  # 줄 이름(화면의 키) — 이름은 members 에
        "role": "admin",
        "gw_account": "ubuntu",
        "server_account": "ubuntu",
        "note": "appuser 는 sudo -iu appuser",
        "members": members,
        "names_note": names_note,
        "where": [{"env": e["env"], "service": s["name"]} for e in out_envs for s in e["services"]],
    }
    rows = [admins] + sorted(people.values(), key=lambda p: p["email"])
    return {**base, "state": "ok", "envs": out_envs, "people": rows, "can_edit": can_edit(user),
            "names": {"state": names["state"], "reasons": names["reasons"]}}
