"""서버 상태 — 서버가 스스로 적는 상태 파일(예: IdP 서버 status.json)을 수집기가 읽어 올리고, 화면 맨 위에 한 줄로 보여 준다.

왜: 서버(systemd)가 실패를 적고 있어도 보는 사람이 없으면 장애를 오래 모른다 — 보이는 자리에 꺼내 둔다.

판정은 조회할 때 지금 시각으로 한다. 규칙은 하나 — '못 봤다' 를 '정상' 으로 적지 않는다.
- ok=false 이거나 problems · unread 가 하나라도 있으면 경보(alert) — problems 와 unread 를 둘 다 보여 준다
- 파일이 낡았으면(written_at 이 갱신 주기 × 배수보다 오래) 경보 — 적는 쪽 타이머가 죽어도 파일은 그대로 남으니까
- 파일을 못 읽었거나 · 수집기가 한동안 안 올렸거나 · 기록 시각을 못 읽으면 모름(unknown) — 초록으로 두지 않는다
- 줄이 아예 없으면(기능을 안 켬) 아무것도 안 보여 준다
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..config import settings
from ..db import get_db
from ..models import HostStatus

router = APIRouter(prefix="/api/host-status", tags=["host-status"])

DEFAULT_INTERVAL = 60
# 수집기는 파일이 그대로여도 1분마다 다시 올린다 — '수집기가 멈췄다' 는 파일 주기와 따로 이것 기준으로(최소 3번 놓침)
COLLECTOR_SILENCE_MIN_SECONDS = 180


class StatusIn(BaseModel):
    source: str
    reader: str | None = None
    read_ok: bool
    read_error: str | None = None
    written_at: str | None = None
    host: str | None = None
    interval_seconds: int | None = None
    ok: bool | None = None
    problems: list[str] = []
    unread: list[str] = []
    signals: dict | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _list(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw or "[]")
    except ValueError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def _ago(sec: float) -> str:
    if sec < 60:
        return f"{int(sec)}초"
    m = int(sec // 60)
    return f"{m}분" if m < 120 else f"{m // 60}시간"


def judge(r: HostStatus, now: datetime, factor: float) -> dict:
    """한 줄 → {state: ok | alert | unknown, reasons: [...], …}. 화면은 state 로 초록 · 빨강 · 회색."""
    interval = r.interval_seconds or DEFAULT_INTERVAL
    limit = factor * interval
    problems, unread = _list(r.problems), _list(r.unread)
    written, received = _parse(r.written_at), _parse(r.received_at)
    out = {
        "source": r.source, "host": r.host, "reader": r.reader, "written_at": r.written_at, "received_at": r.received_at,
        "interval_seconds": interval, "stale_after_seconds": int(limit), "problems": problems, "unread": unread,
        "read_error": r.read_error, "signals": json.loads(r.signals) if r.signals else None,
        "written_age_seconds": int((now - written).total_seconds()) if written else None,
    }
    reasons: list[str] = []
    if received is None or (now - received).total_seconds() > max(limit, COLLECTOR_SILENCE_MIN_SECONDS):
        reasons.append(f"수집기가 {_ago((now - received).total_seconds())}째 상태를 안 올림" if received else "수집기가 올린 적 없음")
        return {**out, "state": "unknown", "reasons": reasons}
    if not r.read_ok:
        return {**out, "state": "unknown", "reasons": [f"상태 파일을 못 읽음 — {r.read_error or '이유 모름'}"]}
    if written is None:
        return {**out, "state": "unknown", "reasons": [f"기록 시각을 못 읽음({r.written_at!r})"]}
    if (now - written).total_seconds() > limit:
        reasons.append(f"상태 기록이 {_ago((now - written).total_seconds())}째 멈춤 — 적는 쪽 타이머 확인")
    if r.ok is not True and not problems and not unread:
        reasons.append("ok=false 인데 이유가 비어 있음")
    # ok 가 참이어도 problems · unread 가 하나라도 있으면 믿지 않음 — 둘 다 비고 ok 일 때만 정상
    state = "alert" if reasons or problems or unread or r.ok is not True else "ok"
    return {**out, "state": state, "reasons": reasons}


@router.post("", dependencies=[Depends(require_runner)])
def upload(body: StatusIn, db: Session = Depends(get_db)) -> dict:
    r = db.query(HostStatus).filter(HostStatus.source == body.source).first()
    if r is None:
        r = HostStatus(source=body.source)
        db.add(r)
    r.reader = body.reader
    r.received_at = _now().isoformat(timespec="seconds")
    r.read_ok = body.read_ok
    r.read_error = body.read_error
    if body.read_ok:  # 못 읽었으면 마지막으로 읽은 내용은 남겨 둠(화면에 '마지막 기록')
        r.written_at = body.written_at
        r.host = body.host
        r.interval_seconds = body.interval_seconds
        r.ok = body.ok
        r.problems = json.dumps(body.problems, ensure_ascii=False)
        r.unread = json.dumps(body.unread, ensure_ascii=False)
        r.signals = json.dumps(body.signals, ensure_ascii=False) if body.signals is not None else None
    db.commit()
    return {"ok": True}


@router.get("")
def list_status(db: Session = Depends(get_db)) -> list[dict]:
    now = _now()
    return [judge(r, now, settings.ct_host_status_stale_factor) for r in db.query(HostStatus).order_by(HostStatus.source).all()]
