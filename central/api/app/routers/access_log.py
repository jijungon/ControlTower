"""접속 기록 — 금고(IdP)가 SSH 인증서(도장)를 내준 기록을 IdP 서버가 요약 파일로 적고, 수집기가 읽어 올린다. 운영자만 본다.

1단계: 누가(이메일) · 언제 · 어느 환경 · 어떤 계정(ubuntu / appuser / 개인 gw 계정) 인증서를 받았나 · 발급/거부.
       '서버에 실제로 들어간 기록' 이 아니다 — 인증서는 30분~1시간 쓸 수 있고, 여러 번 쓰거나 안 쓸 수도 있다.
       어느 gw · 서버로 들어갔는지는 금고 기록에 없다(2단계 gw 접속 기록부터).

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
from ..models import AccessLogSnapshot
from .host_status import COLLECTOR_SILENCE_MIN_SECONDS, DEFAULT_INTERVAL, _ago, _now, _parse

router = APIRouter(prefix="/api/access-log", tags=["access-log"])


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
    return notes


def judge(r: AccessLogSnapshot | None, now: datetime, factor: float) -> dict:
    """한 줄 → {state: off | unknown | ok, reasons, notes, …}. unknown 이면 events 를 비워 '지금 기록' 처럼 보이지 않게."""
    base = {"state": "off", "reasons": [], "notes": [], "written_at": None, "host": None, "window_days": None,
            "files_read": None, "lines_read": None, "written_age_seconds": None, "stale_after_seconds": None, "events": []}
    if r is None:
        return {**base, "reasons": ["아직 연결 전 — 수집기가 접속 기록을 올린 적이 없어요"]}
    written, received = _parse(r.written_at), _parse(r.received_at)
    limit = factor * (r.interval_seconds or DEFAULT_INTERVAL)
    out = {**base, "written_at": r.written_at, "host": r.host, "window_days": r.window_days, "files_read": r.files_read,
           "lines_read": r.lines_read, "stale_after_seconds": int(limit),
           "written_age_seconds": int((now - written).total_seconds()) if written else None}

    def unknown(why: str) -> dict:
        return {**out, "state": "unknown", "reasons": [why]}

    if received is None or (now - received).total_seconds() > max(limit, COLLECTOR_SILENCE_MIN_SECONDS):
        return unknown(f"못 봄 — 수집기가 {_ago((now - received).total_seconds())}째 접속 기록을 안 올림" if received else "못 봄 — 수집기가 올린 적 없음")
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


@router.post("", dependencies=[Depends(require_runner)])
def upload(body: AccessIn, db: Session = Depends(get_db)) -> dict:
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
    return judge(r, now, settings.ct_host_status_stale_factor)
