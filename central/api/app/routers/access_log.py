"""접속 기록 — 금고(IdP)가 SSH 인증서(도장)를 내준 기록을 IdP 서버가 요약 파일로 적고, 수집기가 읽어 올린다. 운영자만 본다.

1단계(GET /api/access-log, source 'idp'): 누가(이메일) · 언제 · 어느 환경 · 어떤 계정(ubuntu / appuser / 개인 gw 계정)
       인증서를 받았나 · 발급/거부. '서버에 실제로 들어간 기록' 이 아니다 — 인증서는 30분~1시간 쓸 수 있다.
2단계(GET /api/access-log/gw-logins, source 'idp-gw'): 그 인증서로 어느 gw 에 · 언제 · 어떤 계정으로 실제로 들어갔나.
       gw 가 5분마다 자기 sshd 기록을 금고에 보고 → IdP 가 모아 gw-logins.jsonl. 인증서 번호(serial)로 1단계와 잇는 건 화면.
       '보고 안 하는 gw 가 있다' 를 '거기엔 아무도 안 들어갔다' 로 보이지 않게 gw 마다 보고 상태를 같이 준다(gw_status).
       금고 목록과 잇는 건 gw 가 스스로 적어 보낸 (env, service) 뿐 — 출입증 이름(gw)은 관리자가 지은 별칭이라 짐작하지 않는다.

판정은 조회할 때 지금 시각으로 한다. 규칙은 하나 — '못 봤다' 를 '아무도 안 들어왔다' 로 보이지 않는다.
- 아무것도 안 올라왔으면 연결 전(off) — 수집기가 이 기능을 안 켬
- 못 봄(unknown) — 표는 안 보여 줌:
  요약 파일이 없음(IdP 반영 전 포함) · 못 읽음 / IdP 가 금고 기록을 못 읽음(머리의 read_ok=false, why)
  / 기록이 멈춤(written_at 이 주기 × 배수보다 오래 — 서버 상태 한 줄과 같은 CT_HOST_STATUS_STALE_FACTOR)
  / 수집기가 멈춤 / 읽은 금고 기록 파일이 0개(files_read=0) · 줄이 0줄(lines_read=0, 있을 때만)
- 그 밖엔 ok — 0건이면 '최근 N일 접속 없음'. 잘림 · 깨진 줄 · 건수가 안 맞으면 notes 로 알림(실패로 보지 않음)

누가 보나: 운영자(server-admin)만. 개발자는 main.py 의 '서버 탭만' 이 이미 막고(403), viewer 등은 여기서 403.
그룹을 모르면(CT_AUTH_MODE=none) '누군지 모름(no_identity)' — 로컬 미리보기(CT_ACCESS_LOCAL_PREVIEW)만 연다.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import Principal, auth_mode, current_user, require_runner
from ..config import settings
from ..db import get_db
from ..inventory_source import InventoryError, fetch_inventory
from ..models import AccessLogSnapshot
from . import idp_people
from .host_status import COLLECTOR_SILENCE_MIN_SECONDS, DEFAULT_INTERVAL, _ago, _now, _parse

router = APIRouter(prefix="/api/access-log", tags=["access-log"])

GW_SOURCE = "idp-gw"  # gw-logins.jsonl 줄 — 발급 기록('idp')과 같은 표, 다른 줄
GW_EVERY = 300        # gw 보고 주기(초) — 칸이 없을 때
GW_STALE_FACTOR = 3   # 마지막 보고가 주기 × 3(보통 15분)보다 오래면 '보고 끊김'(IdP 와 정한 값)


class AccessIn(BaseModel):
    source: str
    reader: str | None = None
    read_ok: bool
    read_error: str | None = None
    written_at: str | None = None
    host: str | None = None
    interval_seconds: int | None = None
    window_days: int | None = None
    audit_ok: bool | None = None
    audit_reason: str | None = None
    files_read: int | None = None
    lines_read: int | None = None
    source_bad_lines: int | None = None
    header_events: int | None = None
    event_lines: int | None = None
    bad_lines: int = 0
    truncated: bool = False
    events: list[dict] = []


class GwLoginsIn(AccessIn):
    reports: int | None = None
    gws: list[dict] | None = None  # None = 파일 머리에 gws 가 없음(gw 마다 상태 모름)
    bad_gws: int = 0


def _viewer(user: Principal) -> str | None:
    """'admin' · 'denied' · None(누군지 모름)."""
    if auth_mode() not in ("oidc", "proxy"):
        return "admin" if settings.ct_access_local_preview else None
    if not user.authenticated:
        return None
    return "admin" if "server-admin" in user.groups else "denied"


def _notes(r: AccessLogSnapshot, shown: int) -> list[str]:
    notes = []
    if r.truncated:
        notes.append(f"최근 {r.header_events or shown}건까지만 받았어요")
    if r.source_bad_lines:
        notes.append(f"IdP 가 금고 기록에서 못 읽은 줄 {r.source_bad_lines}개")
    if r.bad_lines:
        notes.append(f"깨져서 뺀 줄 {r.bad_lines}개")
    if r.header_events is not None and r.event_lines is not None and r.header_events != r.event_lines:
        notes.append(f"파일 머리에는 {r.header_events}건인데 {r.event_lines}줄을 받았어요")
    if r.bad_gws:
        notes.append(f"깨져서 뺀 gw 보고 칸 {r.bad_gws}개")
    return notes


def judge(r: AccessLogSnapshot | None, now: datetime, factor: float, what: str = "접속 기록") -> dict:
    """한 줄 → {state: off | unknown | ok, reasons, notes, …}. unknown 이면 events 를 비워 '지금 기록' 처럼 보이지 않게."""
    base = {"state": "off", "reasons": [], "notes": [], "written_at": None, "host": None, "window_days": None,
            "files_read": None, "lines_read": None, "written_age_seconds": None, "stale_after_seconds": None, "events": []}
    if r is None:
        return {**base, "reasons": [f"아직 연결 전 — 수집기가 {what}을 올린 적이 없어요"]}
    written, received = _parse(r.written_at), _parse(r.received_at)
    limit = factor * (r.interval_seconds or DEFAULT_INTERVAL)
    out = {**base, "written_at": r.written_at, "host": r.host, "window_days": r.window_days, "files_read": r.files_read,
           "lines_read": r.lines_read, "stale_after_seconds": int(limit),
           "written_age_seconds": int((now - written).total_seconds()) if written else None}

    def unknown(why: str) -> dict:
        return {**out, "state": "unknown", "reasons": [why]}

    if received is None or (now - received).total_seconds() > max(limit, COLLECTOR_SILENCE_MIN_SECONDS):
        return unknown(f"못 봄 — 수집기가 {_ago((now - received).total_seconds())}째 {what}을 안 올림" if received else "못 봄 — 수집기가 올린 적 없음")
    if not r.read_ok:
        if r.read_error == "파일 없음":
            return unknown("못 봄 — 요약 파일이 없어요(IdP 서버가 아직 안 만들었거나 지워짐)")
        return unknown(f"못 봄 — 요약 파일을 못 읽음: {r.read_error or '이유 모름'}")
    if r.audit_ok is not True:
        return unknown(f"못 봄 — IdP 가 금고 기록을 못 읽음: {r.audit_reason or '이유 모름'}")
    if written is None:
        return unknown(f"못 봄 — 기록 시각을 못 읽음({r.written_at!r})")
    if (now - written).total_seconds() > limit:
        return unknown(f"멈춤 — 요약 기록이 {_ago((now - written).total_seconds())}째 그대로예요(IdP 쪽 타이머 확인)")
    if r.files_read == 0:
        return unknown("못 봄 — 금고 기록 파일을 하나도 못 읽었어요")
    if r.lines_read == 0:  # 읽긴 했는데 금고 기록이 비었다 — 기록이 안 쌓이는 것이지 '아무도 안 들어옴' 이 아님
        return unknown("못 봄 — 금고 기록이 비어 있어요(IdP 가 읽은 감사 기록이 0줄)")
    try:
        events = json.loads(r.events or "[]")
    except ValueError:
        return unknown("못 봄 — 저장된 기록이 깨짐")
    events = sorted((e for e in events if isinstance(e, dict)), key=lambda e: str(e.get("at", "")), reverse=True)
    return {**out, "state": "ok", "notes": _notes(r, len(events)), "events": events}


def gw_status(g: dict, now: datetime) -> dict:
    """gw 한 대의 마지막 보고 → {state: ok | unknown(못 봄) | stale(보고 끊김), reason}. 보고 안 함(silent)은 gw_logins_view 가."""
    every = g.get("every_seconds") or GW_EVERY
    last = _parse(g.get("last_report_at"))
    age = int((now - last).total_seconds()) if last else None
    out = {"gw": g.get("gw"), "host": g.get("host"), "env": g.get("env"), "service": g.get("service"),
           "last_report_at": g.get("last_report_at"), "age_seconds": age,
           "every_seconds": every, "files_read": g.get("files_read"), "lines_read": g.get("lines_read")}
    if g.get("read_ok") is not True:  # gw 가 자기 sshd 기록을 못 읽음 — '아무도 안 들어옴' 이 아님
        return {**out, "state": "unknown", "reason": f"못 봄 — gw 가 자기 접속 기록을 못 읽음: {g.get('why') or '이유 모름'}"}
    if age is None:
        return {**out, "state": "unknown", "reason": "못 봄 — 마지막 보고 시각을 못 읽음"}
    if age > GW_STALE_FACTOR * every:
        return {**out, "state": "stale", "reason": f"보고 끊김 — 마지막 보고가 {_ago(age)} 전이에요(gw 타이머 · 출입증 확인)"}
    return {**out, "state": "ok", "reason": None}


def _listed_gws() -> dict:
    """금고 목록(서버 탭)에서 gw 가 있는 항목 → {"state": "ok", "keys": [(env, service), …]}.
    못 읽으면 {"state": "off" | "error", "reason"} — 그땐 '보고 안 함' 을 못 가린다."""
    try:
        inv = fetch_inventory()
    except InventoryError as exc:
        if str(exc) == "off":
            return {"state": "off", "reason": "금고 목록(서버 탭)에 연결 전이라 보고 안 하는 gw 가 있는지 몰라요"}
        return {"state": "error", "reason": f"금고 목록을 못 읽어 보고 안 하는 gw 가 있는지 몰라요: {exc}"}
    keys = [(env, svc) for env, services in sorted(inv.items()) for svc, v in sorted((services or {}).items())
            if isinstance(v, dict) and isinstance(v.get("gw"), dict) and v["gw"].get("host")]
    return {"state": "ok", "keys": keys}


def gw_logins_view(r: AccessLogSnapshot | None, now: datetime, factor: float) -> dict:
    """gw-logins 한 줄 → judge(파일 상태) + gw 마다 보고 상태. 파일이 ok 일 때만 gw 상태 · 금고 목록을 본다.

    link(금고 목록과): listed(목록에 있음) · not_listed(보낸 env · service 가 목록에 없음) · unlinked(env · service 를 안 보냄
    — trust 전 · 옛 꾸러미, 목록과 못 이음) · unknown(목록을 못 읽음). 목록에 있는데 이어지는 보고가 없는 항목은 줄을 더한다:
    못 잇는 보고가 0개면 silent(보고 안 함), 1개라도 있으면 maybe_silent — 그 보고가 이 항목의 gw 일 수 있어 단정하지 않는다."""
    out = {**judge(r, now, factor, "gw 접속 기록"), "reports": None, "gws": [], "gws_known": False, "reporting": 0,
           "unlinked": 0, "inventory": {"state": "skipped", "reason": None}}
    if out["state"] != "ok":
        return out
    try:
        raw = None if r.gws is None else json.loads(r.gws)
    except ValueError:
        raw = None
    if not isinstance(raw, list):  # 머리에 gws 가 없었음 — gw 마다 상태를 모름(보고 안 함과 구분 못 함)
        return {**out, "reports": r.reports, "notes": out["notes"] + ["gw 마다 보고 상태가 파일에 없어요 — 보고 안 하는 gw 를 가릴 수 없어요"]}
    gws = [gw_status(g, now) for g in raw if isinstance(g, dict)]
    unlinked = sum(not (g["env"] and g["service"]) for g in gws)
    inv = _listed_gws()
    keys = set(inv.get("keys", []))
    for g in gws:
        if not (g["env"] and g["service"]):
            g["link"] = "unlinked"
        else:
            g["link"] = "unknown" if inv["state"] != "ok" else "listed" if (g["env"], g["service"]) in keys else "not_listed"
    if inv["state"] == "ok":
        seen = {(g["env"], g["service"]) for g in gws if g["link"] == "listed"}
        if unlinked:
            state, why = "maybe_silent", f"보고 안 함일 수 있음 — 목록과 못 잇는 보고 {unlinked}개"
        else:
            state, why = "silent", "보고 안 함 — 금고 목록에 있는 gw 인데 이어지는 보고가 없어요(gw 보고 켜기 · trust 확인)"
        gws += [{"gw": None, "host": None, "env": env, "service": svc, "last_report_at": None, "age_seconds": None,
                 "every_seconds": None, "files_read": None, "lines_read": None, "link": "listed", "state": state, "reason": why}
                for env, svc in inv["keys"] if (env, svc) not in seen]
    gws.sort(key=lambda g: (g["gw"] is None, str(g["gw"] or ""), str(g["env"] or ""), str(g["service"] or "")))
    return {**out, "reports": r.reports, "gws": gws, "gws_known": True, "unlinked": unlinked,
            "reporting": sum(g["state"] == "ok" for g in gws), "inventory": {"state": inv["state"], "reason": inv.get("reason")}}


def _save(db: Session, body: AccessIn) -> AccessLogSnapshot:
    r = db.query(AccessLogSnapshot).filter(AccessLogSnapshot.source == body.source).first()
    if r is None:
        r = AccessLogSnapshot(source=body.source)
        db.add(r)
    r.reader, r.received_at = body.reader, _now().isoformat(timespec="seconds")
    r.read_ok, r.read_error = body.read_ok, body.read_error
    # 올 때마다 통째로 바꾼다 — 못 읽었으면 내용도 비운다(지난 기록을 지금 것처럼 남기지 않음)
    keep = body.read_ok
    for k in ("written_at", "host", "interval_seconds", "window_days", "audit_ok", "audit_reason", "files_read",
              "lines_read", "source_bad_lines", "header_events", "event_lines"):
        setattr(r, k, getattr(body, k) if keep else None)
    r.bad_lines = body.bad_lines if keep else 0
    r.truncated = body.truncated if keep else False
    r.events = json.dumps(body.events if keep else [], ensure_ascii=False)
    return r


@router.post("", dependencies=[Depends(require_runner)])
def upload(body: AccessIn, db: Session = Depends(get_db)) -> dict:
    if body.source == GW_SOURCE:  # gw 줄을 발급 기록 모양으로 덮지 않게
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{GW_SOURCE} 는 /api/access-log/gw-logins 로 올려요")
    _save(db, body)
    db.commit()
    return {"ok": True}


@router.post("/gw-logins", dependencies=[Depends(require_runner)])
def upload_gw_logins(body: GwLoginsIn, db: Session = Depends(get_db)) -> dict:
    if body.source != GW_SOURCE:  # 발급 기록 줄('idp')을 gw 모양으로 덮지 않게
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"gw 접속 기록의 source 는 {GW_SOURCE} 여야 해요")
    r = _save(db, body)
    keep = body.read_ok
    r.reports = body.reports if keep else None
    r.gws = json.dumps(body.gws, ensure_ascii=False) if keep and body.gws is not None else None
    r.bad_gws = body.bad_gws if keep else None
    db.commit()
    return {"ok": True}


@router.get("")
def get_access_log(user: Principal = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    who = _viewer(user)
    if who == "denied":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "운영자만 볼 수 있어요")
    now = _now()
    if who is None:
        return {**judge(None, now, settings.ct_host_status_stale_factor), "state": "no_identity",
                "reasons": ["로그인 정보(그룹)를 몰라 보여 줄 수 없어요 — 운영자만 보는 기록이에요"]}
    r = db.query(AccessLogSnapshot).filter(AccessLogSnapshot.source == "idp").first()
    # 이름표(이메일 → 이름)는 따로 붙인다 — '누가' 칸 이메일 옆에. 이름표를 모르면 people 이 비어 이메일만 보인다
    return {**judge(r, now, settings.ct_host_status_stale_factor), "names": idp_people.for_log(db)}


@router.get("/gw-logins")
def get_gw_logins(user: Principal = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    who = _viewer(user)  # 발급 기록과 같은 선 — 운영자만(개발자는 main.py 가 먼저 막음)
    if who == "denied":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "운영자만 볼 수 있어요")
    now = _now()
    if who is None:
        return {**gw_logins_view(None, now, settings.ct_host_status_stale_factor), "state": "no_identity",
                "reasons": ["로그인 정보(그룹)를 몰라 보여 줄 수 없어요 — 운영자만 보는 기록이에요"]}
    r = db.query(AccessLogSnapshot).filter(AccessLogSnapshot.source == GW_SOURCE).first()
    return gw_logins_view(r, now, settings.ct_host_status_stale_factor)
