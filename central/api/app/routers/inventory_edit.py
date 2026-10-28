"""서버 탭 '목록 고치기' — 금고 목록(inventory/<환경>/<서비스>)의 gw · 서버를 운영자가 고친다. 기본 꺼짐.

스위치: CT_INVENTORY_EDIT=1 (기본 0). 꺼져 있으면 화면에 고치기가 없고, 이 API 는 403 '꺼져 있음'.
  켜도 금고 쪽 ct-inventory 정책에 inventory/data/* 쓰기(update)가 없으면 금고가 거절한다 — 그 까닭을 그대로 보인다.

누가: 운영자(server-admin)만. 개발자는 main.py 의 '서버 탭만'(DEVELOPER_OPEN_API 밖)이 먼저 403,
  viewer 등은 여기서 403. 그룹을 모르면(none 모드 · proxy 인데 서명 맞는 토큰 없음) '누군지 모름' 403
  — 로컬 미리보기(CT_ACCESS_LOCAL_PREVIEW)만 연다(access.py 와 같은 선).
무엇을: 한 항목의 gw(host · port)와 servers(이름 → 주소)만. users 는 손대지 않는다 — idp-login user add 가
  gw 에 OS 계정도 만들어서, 목록만 바꾸면 gw 와 어긋난다. 새 서비스 · 서비스 지우기도 gw 의 idp-login 으로만.
어떻게(idp-login 이 같은 때 써도 안전하게):
  1) GET  — 그 항목을 캐시 없이 읽어 판 번호(version)를 화면에 준다
  2) POST …/preview — 저장 전 확인: 지금 금고 판과 비교한 '바뀌는 것' 목록(쓰지 않음)
  3) PUT  — 다시 읽어 판이 같은지 보고, 읽은 그대로에서 gw · servers 만 바꾼 **통째** 를 cas=그 판 으로 쓴다
     → 그 사이 누가 고쳤으면 금고가 거절(409 '다시 불러온 뒤 고쳐 주세요'). 반쪽짜리 객체는 안 쓴다.
     쓰기는 PUT 이라 다른 사이트의 폼으로는 못 보낸다(브라우저가 사전 확인에서 막음).
누가 고쳤나(updated_by): 금고 안에는 안 적고 ControlTower 작업이력에 '항목 · 판 번호 · 이메일' 로 남긴다.
  - custom_metadata 는 metadata 쓰기 권한이 더 필요하고(판 보관 수 · cas 강제 같은 설정까지 바뀜),
    판마다가 아니라 항목에 하나라서 다음에 idp-login 이 고쳐도 'CT 의 누구' 로 남는다.
  - data 에 칸을 더하면 idp-login 이 읽고 다시 쓰는 모양이 바뀐다(모르는 칸을 지우거나 옮기면 틀린 이름이 남음).
  작업이력에 '이 판은 누가' 를 적어 두면, 지금 판이 CT 에서 쓴 판이 아니면 'CT 밖(idp-login 등)' 이라고 정확히 말할 수 있다.
  언제(updated_at)는 금고가 판마다 적는 created_time 그대로.
  작업이력에는 주소를 적지 않는다(이름 · 바뀐 종류만) — 작업이력은 viewer 도 보지만 목록 주소는 운영자만 본다.
"""
from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import Principal, auth_mode, current_user
from ..config import settings
from ..db import get_db
from ..inventory_source import (
    ENVS,
    InventoryConflict,
    InventoryError,
    InventoryUnknown,
    _login,
    read_entry,
    write_entry,
)
from ..models import AuditLog

router = APIRouter(prefix="/api/inventory", tags=["inventory-edit"])

# 이름 · 주소는 idp-login 명령(idp-login ssh <계정> <환경> <서버>)에 그대로 들어간다 — '-' 로 시작 금지(옵션으로 읽힘)
NAME_RE = re.compile(r"^(?!-)(?!\.{1,2}$)[A-Za-z0-9._-]{1,63}$")
ADDR_RE = re.compile(r"^(?!-)[A-Za-z0-9.:-]{1,253}$")  # IPv4 · IPv6 · 호스트 이름
MAX_SERVERS = 200
CONFLICT = "다른 곳(idp-login 등)에서 먼저 고쳤어요 — 다시 불러온 뒤 고쳐 주세요"
LOCAL_PREVIEW_ACTOR = "로컬 미리보기(로그인 없음)"


def edit_on() -> bool:
    return bool(settings.ct_inventory_edit)


def _actor(user: Principal) -> tuple[str | None, str]:
    """(작업이력에 남길 이름, 못 고치는 까닭). 이름이 None 이면 못 고친다."""
    if auth_mode() not in ("oidc", "proxy"):
        if settings.ct_access_local_preview:
            return LOCAL_PREVIEW_ACTOR, ""
        return None, "누군지 몰라요(로그인 그룹을 모름) — 고칠 수 없어요"
    if not user.authenticated:
        return None, "누군지 몰라요(서명 맞는 로그인 토큰이 없음) — 고칠 수 없어요"
    if "server-admin" in user.groups:
        return user.email or "server-admin", ""
    return None, "운영자(server-admin)만 목록을 고칠 수 있어요"


def can_edit(user: Principal) -> bool:
    """화면에 '고치기' 를 보일까 — /api/access 가 같이 돌려준다."""
    return edit_on() and _actor(user)[0] is not None


def _editor(user: Principal = Depends(current_user)) -> str:
    """세 API 의 문지기 — 몸통(JSON) 검사보다 먼저 돈다(권한 없는 사람에게 422 대신 403)."""
    if not edit_on():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "목록 고치기가 꺼져 있어요(CT_INVENTORY_EDIT) — 지금은 gw 에서 idp-login 으로 고쳐요")
    actor, why = _actor(user)
    if actor is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, why)
    if (settings.ct_inventory_mode or "off").strip().lower() != "vault":
        raise HTTPException(status.HTTP_409_CONFLICT, "금고 목록에 연결 전이에요(CT_INVENTORY_MODE=off) — 고칠 목록이 없어요")
    return actor


def _where(env: str, service: str) -> None:
    if env not in ENVS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"없는 환경: {env}")
    if not NAME_RE.match(service):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"서비스 이름 모양이 이상해요: {service}")


class GwIn(BaseModel):
    host: str
    port: int = Field(22, ge=1, le=65535)


class EditIn(BaseModel):
    version: int  # 고치기 시작할 때 읽은 판 — 이 판 그대로일 때만 쓴다
    gw: GwIn | None = None  # None = gw 는 그대로
    servers: dict[str, str]  # 고친 뒤 서버 전부(이름 → 주소)


def _check(body: EditIn) -> None:
    bad = []
    if body.gw is not None and not ADDR_RE.match(body.gw.host):
        bad.append(f"gw 주소 '{body.gw.host}'")
    if len(body.servers) > MAX_SERVERS:
        bad.append(f"서버 {len(body.servers)}개(최대 {MAX_SERVERS})")
    for name, addr in body.servers.items():
        if not NAME_RE.match(name):
            bad.append(f"서버 이름 '{name}'")
        if not ADDR_RE.match(addr):
            bad.append(f"'{name}' 의 주소 '{addr}'")
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "모양이 이상해요: " + ", ".join(bad) + " — 이름은 영문 · 숫자 · . _ -, 주소는 IP 나 호스트 이름",
        )


def _read(env: str, service: str, token: str) -> dict:
    try:
        cur = read_entry(env, service, token)
    except InventoryError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"목록 모름 — 금고를 못 읽었어요: {exc}") from exc
    if cur is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"금고에 {env}/{service} 목록이 없어요 — 새 서비스는 gw 에서 idp-login service add 로"
        )
    if not isinstance(cur["version"], int):
        raise HTTPException(status.HTTP_409_CONFLICT, "금고가 판 번호를 안 줘서 안전하게 고칠 수 없어요(KV v2 가 아님?)")
    data = cur["data"]
    servers, gw = data.get("servers"), data.get("gw")
    if servers is not None and not (isinstance(servers, dict) and all(isinstance(v, str) for v in servers.values())):
        raise HTTPException(status.HTTP_409_CONFLICT, "금고의 servers 모양이 예상과 달라 고치지 않아요 — gw 에서 idp-login 으로")
    if gw is not None and not (isinstance(gw, dict) and str(gw.get("port", 22)).isdigit()):
        raise HTTPException(status.HTTP_409_CONFLICT, "금고의 gw 모양이 예상과 달라 고치지 않아요 — gw 에서 idp-login 으로")
    return cur


def _apply(data: dict, body: EditIn) -> dict:
    """읽은 통째에서 gw · servers 만 바꾼 새 통째. users 와 모르는 칸은 그대로(깊은 복사)."""
    new = copy.deepcopy(data)
    if body.gw is not None:
        old_gw = data.get("gw") or {}
        gw = dict(old_gw)
        if gw.get("host") != body.gw.host:
            gw["host"] = body.gw.host
        old_port = gw.get("port", 22)
        if str(old_port) != str(body.gw.port):  # 22 를 22 로 두면 칸을 새로 만들지 않는다 · 글자로 적혀 있었으면 글자로
            gw["port"] = str(body.gw.port) if isinstance(old_port, str) else body.gw.port
        if gw != old_gw:
            new["gw"] = gw
    old_servers = data.get("servers") or {}
    servers = {n: body.servers[n] for n in old_servers if n in body.servers}  # 있던 순서 그대로
    servers.update({n: a for n, a in body.servers.items() if n not in servers})
    if servers != old_servers:  # 같으면 칸을 건드리지 않는다(없던 servers 를 빈 칸으로 만들지 않음)
        new["servers"] = servers
    return new


def changes(old: dict, new: dict) -> list[dict]:
    """바뀌는 것 — 화면 확인용(주소 포함). 이름은 같은 주소 하나가 빠지고 하나가 생기면 '이름 바꿈'."""
    out: list[dict] = []
    og, ng = old.get("gw") or {}, new.get("gw") or {}
    if og.get("host") != ng.get("host"):
        out.append({"kind": "gw_host", "from": og.get("host"), "to": ng.get("host")})
    if str(og.get("port", 22)) != str(ng.get("port", 22)):
        out.append({"kind": "gw_port", "from": og.get("port", 22), "to": ng.get("port", 22)})
    os_, ns = old.get("servers") or {}, new.get("servers") or {}
    gone = [n for n in os_ if n not in ns]
    came = [n for n in ns if n not in os_]
    renamed = set()
    for g in gone:
        same_from = [x for x in gone if os_[x] == os_[g]]
        same_to = [c for c in came if ns[c] == os_[g]]
        if len(same_from) == 1 and len(same_to) == 1:
            out.append({"kind": "server_rename", "name": same_to[0], "from": g, "to": same_to[0], "addr": os_[g]})
            renamed.update({g, same_to[0]})
    out += [{"kind": "server_remove", "name": n, "from": os_[n]} for n in gone if n not in renamed]
    out += [{"kind": "server_add", "name": n, "to": ns[n]} for n in came if n not in renamed]
    out += [{"kind": "server_addr", "name": n, "from": os_[n], "to": ns[n]} for n in os_ if n in ns and os_[n] != ns[n]]
    return out


KIND_WORD = {
    "gw_host": "gw 주소 바뀜", "gw_port": "gw 포트 바뀜", "server_add": "서버 추가",
    "server_remove": "서버 뺌", "server_addr": "서버 주소 바뀜", "server_rename": "서버 이름 바뀜",
}


def _history(c: dict) -> str:
    """작업이력 한 조각 — 이름 · 종류만(주소 · 포트 값은 안 적음)."""
    if c["kind"] == "server_rename":
        return f"{KIND_WORD[c['kind']]} {c['from']} → {c['to']}"
    return KIND_WORD[c["kind"]] + (f" {c['name']}" if c.get("name") else "")


VERSION_RE = re.compile(r"^v(\d+) → v(\d+)")


def _last_edit(db: Session, env: str, service: str, version: int) -> dict:
    """지금 판을 누가 썼나 — CT 작업이력에 그 판이 있으면 그 사람, 없으면 'CT 밖(idp-login 등)'."""
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action == "inventory.edit", AuditLog.target_id == f"{env}/{service}")
        .order_by(AuditLog.id.desc())
        .limit(50)
        .all()
    )
    for r in rows:
        m = VERSION_RE.match(r.detail or "")
        if m and int(m.group(2)) == version:
            return {"here": True, "by": r.actor, "at": r.created_at}
    return {"here": False, "by": None, "at": None}


@router.get("/{env}/{service}")
def read_one(env: str, service: str, actor: str = Depends(_editor), db: Session = Depends(get_db)) -> dict:
    """고치기 시작 — 캐시 없이 지금 금고 판. users 는 몇 명인지만(여기서 안 고침)."""
    _where(env, service)
    cur = _read(env, service, _token())
    d = cur["data"]
    gw = d.get("gw") or {}
    return {
        "env": env,
        "service": service,
        "version": cur["version"],
        "updated_at": cur["updated_at"],
        "last_edit": _last_edit(db, env, service, cur["version"]),
        "gw": {"host": gw.get("host"), "port": int(gw.get("port", 22))} if gw.get("host") else None,
        "servers": d.get("servers") or {},
        "users_count": len(d.get("users") or {}),
    }


def _plan(env: str, service: str, body: EditIn, token: str) -> tuple[dict, dict, list[dict]]:
    cur = _read(env, service, token)
    if cur["version"] != body.version:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{CONFLICT} (고치기 시작할 때 v{body.version}, 지금 v{cur['version']})")
    new = _apply(cur["data"], body)
    return cur, new, changes(cur["data"], new)


def _token() -> str:
    try:
        return _login()
    except InventoryError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"금고에 못 붙었어요(아무것도 안 바뀜): {exc}") from exc


@router.post("/{env}/{service}/preview")
def preview(env: str, service: str, body: EditIn, actor: str = Depends(_editor)) -> dict:
    """저장 전 확인 — 지금 금고 판과 비교한 '바뀌는 것'. 쓰지 않는다."""
    _where(env, service)
    _check(body)
    cur, _, ch = _plan(env, service, body, _token())
    return {"version": cur["version"], "changes": ch}


@router.put("/{env}/{service}")
def save(env: str, service: str, body: EditIn, actor: str = Depends(_editor), db: Session = Depends(get_db)) -> dict:
    _where(env, service)
    _check(body)
    token = _token()
    cur, new, ch = _plan(env, service, body, token)
    if not ch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "바뀐 게 없어요 — 저장하지 않았어요")
    target = f"{env}/{service}"
    what = " · ".join(_history(c) for c in ch)
    try:
        out = write_entry(env, service, new, cas=cur["version"], token=token)
    except InventoryConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{CONFLICT} (v{cur['version']} 뒤에 바뀜)") from exc
    except InventoryUnknown as exc:
        record(db, "inventory.edit_unknown", actor=actor, target_type="inventory", target_id=target,
               detail=f"v{cur['version']} → ? · {what}")
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"저장됐는지 모름 — 다시 불러와 확인해 주세요: {exc}"
        ) from exc
    except InventoryError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"금고가 저장을 거절했어요(아무것도 안 바뀜): {exc}") from exc
    result = {"saved": True, "version": out["version"], "updated_at": out["updated_at"], "changes": ch}
    try:
        record(db, "inventory.edit", actor=actor, target_type="inventory", target_id=target,
               detail=f"v{cur['version']} → v{out['version']} · {what}")
        db.commit()
    except Exception as exc:  # noqa: BLE001 — 금고에는 이미 저장됨: '안 됨' 으로 보이지 않게 저장은 됐다고 하고 이력 실패만 알린다
        db.rollback()
        result["history_error"] = f"작업이력에 못 남겼어요: {type(exc).__name__}"
    return result
