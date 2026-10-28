"""사람 이름표 — IdP 서버가 5분마다 Authentik 의 server-admin · developer 사람 목록(people.jsonl)을 적고, 수집기가 읽어 올린다.

쓰는 곳(따로 보는 API 는 없다 — 이미 있는 응답에 이름만 붙인다):
  서버 탭(/api/access) — 운영자 줄 'server-admin 그룹 전원' 대신 실제 이름 · 개발자 이메일 옆 이름. 개발자도 본다.
  접속 기록 탭(/api/access-log) — '누가' 칸 이메일 옆 이름. 운영자만.
키는 이메일(소문자) — 금고 목록의 이메일 · 접속 기록의 who 도 소문자로 바꿔 찾는다. 못 찾으면 이메일만(오류 아님 —
두 그룹 어디에도 없는 사람은 파일에 없다).

판정은 조회할 때 지금 시각으로 한다. 규칙은 하나 — '이름을 못 봤다' 를 '운영자 없음' 으로 보이지 않는다.
- 아무것도 안 올라왔으면 연결 전(off)
- 모름(unknown) — 이름을 안 붙인다(people 비움):
  파일 없음 · 못 읽음 / IdP 가 Authentik 을 못 읽음(머리의 read_ok=false, why — 이때 IdP 는 사람 줄을 0줄로 적는다)
  / 기록이 멈춤(written_at 이 주기(300초) × CT_HOST_STATUS_STALE_FACTOR 보다 오래) / 수집기가 멈춤
- 그 밖엔 ok. 깨진 줄 · 사람 수가 안 맞으면 notes 로 알림(실패로 보지 않음)
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..config import settings
from ..db import get_db
from ..models import IdpPeople
from .host_status import COLLECTOR_SILENCE_MIN_SECONDS, _ago, _now, _parse

router = APIRouter(prefix="/api/idp-people", tags=["idp-people"])

DEFAULT_INTERVAL = 300  # IdP 가 5분마다 다시 씀 — 파일 머리에 주기가 없을 때만 이 값


class PeopleIn(BaseModel):
    source: str
    reader: str | None = None
    read_ok: bool
    read_error: str | None = None
    written_at: str | None = None
    host: str | None = None
    interval_seconds: int | None = None
    origin: str | None = None
    list_ok: bool | None = None
    list_reason: str | None = None
    groups: dict[str, int] | None = None
    header_people: int | None = None
    person_lines: int | None = None
    bad_lines: int = 0
    truncated: bool = False
    people: list[dict] = []


def _notes(r: IdpPeople) -> list[str]:
    notes = []
    if r.truncated:
        notes.append("사람이 너무 많아 잘라 받았어요")
    if r.bad_lines:
        notes.append(f"깨져서 뺀 줄 {r.bad_lines}개")
    if r.header_people is not None and r.person_lines is not None and r.header_people != r.person_lines:
        notes.append(f"이름표 머리에는 {r.header_people}명인데 {r.person_lines}줄을 받았어요")
    return notes


def judge(r: IdpPeople | None, now: datetime, factor: float) -> dict:
    """한 줄 → {state: off | unknown | ok, reasons, notes, groups, people}. ok 가 아니면 people 을 비운다."""
    base = {"state": "off", "reasons": [], "notes": [], "written_at": None, "stale_after_seconds": None, "groups": None,
            "people": []}
    if r is None:
        return {**base, "reasons": ["이름표 연결 전 — 수집기가 올린 적이 없어요"]}
    written, received = _parse(r.written_at), _parse(r.received_at)
    limit = factor * (r.interval_seconds or DEFAULT_INTERVAL)
    out = {**base, "written_at": r.written_at, "stale_after_seconds": int(limit)}

    def unknown(why: str) -> dict:
        return {**out, "state": "unknown", "reasons": [why]}

    if received is None or (now - received).total_seconds() > max(limit, COLLECTOR_SILENCE_MIN_SECONDS):
        return unknown(f"수집기가 {_ago((now - received).total_seconds())}째 이름표를 안 올림" if received else "수집기가 올린 적 없음")
    if not r.read_ok:
        if r.read_error == "파일 없음":
            return unknown("이름표 파일이 없어요(IdP 서버가 아직 안 만들었거나 지워짐)")
        return unknown(f"이름표 파일을 못 읽음: {r.read_error or '이유 모름'}")
    if r.list_ok is not True:
        return unknown(f"IdP 가 Authentik 을 못 읽음: {r.list_reason or '이유 모름'}")
    if written is None:
        return unknown(f"기록 시각을 못 읽음({r.written_at!r})")
    if (now - written).total_seconds() > limit:
        return unknown(f"이름표가 {_ago((now - written).total_seconds())}째 그대로예요(IdP 쪽 타이머 확인)")
    try:
        people = json.loads(r.people or "[]")
        groups = json.loads(r.groups) if r.groups else None
    except ValueError:
        return unknown("저장된 이름표가 깨짐")
    people = [p for p in people if isinstance(p, dict)]
    return {**out, "state": "ok", "notes": _notes(r), "groups": groups if isinstance(groups, dict) else None,
            "people": people}


def current(db: Session) -> dict:
    """지금 이름표 — 서버 탭 · 접속 기록 탭이 이름을 붙일 때 쓴다."""
    r = db.query(IdpPeople).filter(IdpPeople.source == "idp").first()
    return judge(r, _now(), settings.ct_host_status_stale_factor)


def shown_name(p: dict) -> str | None:
    """화면에 보일 이름 — Authentik 표시 이름, 없으면 아이디. 둘 다 없으면 None(이메일만 보인다)."""
    return p.get("name") or p.get("username") or None


def by_email(names: dict) -> dict[str, dict]:
    """이메일(소문자) → 사람. 이름표가 ok 가 아니면 빈 것 — 찾는 쪽은 '못 찾음' 과 똑같이 이메일만 보인다."""
    if names.get("state") != "ok":
        return {}
    return {str(p["email"]).strip().lower(): p for p in names["people"] if p.get("email")}


def for_log(db: Session) -> dict:
    """접속 기록 탭용 — {state, reasons, notes, people: {이메일(소문자): {name, active}}}. 운영자만 보는 응답에만 붙인다."""
    names = current(db)
    return {
        "state": names["state"], "reasons": names["reasons"], "notes": names["notes"],
        "people": {e: {"name": shown_name(p), "active": p.get("active") is not False} for e, p in by_email(names).items()},
    }


@router.post("", dependencies=[Depends(require_runner)])
def upload(body: PeopleIn, db: Session = Depends(get_db)) -> dict:
    r = db.query(IdpPeople).filter(IdpPeople.source == body.source).first()
    if r is None:
        r = IdpPeople(source=body.source)
        db.add(r)
    r.reader, r.received_at = body.reader, _now().isoformat(timespec="seconds")
    r.read_ok, r.read_error = body.read_ok, body.read_error
    # 올 때마다 통째로 바꾼다 — 못 읽었으면 내용도 비운다(지난 이름을 지금 것처럼 남기지 않음)
    keep = body.read_ok
    for k in ("written_at", "host", "interval_seconds", "origin", "list_ok", "list_reason", "header_people", "person_lines"):
        setattr(r, k, getattr(body, k) if keep else None)
    r.groups = json.dumps(body.groups, ensure_ascii=False) if keep and body.groups is not None else None
    r.bad_lines = body.bad_lines if keep else 0
    r.truncated = body.truncated if keep else False
    r.people = json.dumps(body.people if keep else [], ensure_ascii=False)
    db.commit()
    return {"ok": True}
