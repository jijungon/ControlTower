"""다시 수집 — 화면 버튼이 요청을 남기고, 수집기(agent)가 가져가 처리한다.

중앙은 키·토큰이 없다(조회 전용). 그래서 수집을 직접 하지 않고 요청만 저장한다.
수집기는 ControlTower 와 같은 서버(또는 PC)에서 돌며 몇 초마다 /claim 으로 요청을 확인 → GitLab 을 다시 읽어 올림 → /finish.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import Collector, CollectRequest

router = APIRouter(prefix="/api/collect", tags=["collect"])

KINDS = {"shape"}  # shape = 빌드·배포 + config (runner shape)
ALIVE_SECONDS = 60  # 이 안에 확인했으면 '수집기 켜짐'
STALE_MINUTES = 15  # 수집 중으로 이만큼 지나면 수집기가 죽은 것 → 실패로
PENDING_MINUTES = 10  # 요청됨으로 이만큼 아무도 안 가져가면 취소(수집기가 꺼져 있던 것)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _out(r: CollectRequest | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id, "kind": r.kind, "status": r.status, "requested_at": r.requested_at,
        "started_at": r.started_at, "finished_at": r.finished_at, "collector": r.collector, "message": r.message,
    }


def _alive(db: Session, now: datetime) -> Collector | None:
    """ALIVE_SECONDS 안에 확인한 수집기(가장 최근)."""
    c = db.query(Collector).order_by(Collector.last_seen_at.desc()).first()
    if c and c.last_seen_at and now - datetime.fromisoformat(c.last_seen_at) <= timedelta(seconds=ALIVE_SECONDS):
        return c
    return None


def _expire(db: Session, now: datetime) -> None:
    """오래 멈춘 요청을 닫음 — 수집 중 STALE_MINUTES(수집기가 도중에 죽음) · 요청됨 PENDING_MINUTES(아무도 안 가져감)."""
    for r in db.query(CollectRequest).filter(CollectRequest.status.in_(("pending", "running"))).all():
        if r.status == "running" and r.started_at and now - datetime.fromisoformat(r.started_at) > timedelta(minutes=STALE_MINUTES):
            r.status, r.finished_at, r.message = "failed", _iso(now), f"{STALE_MINUTES}분 넘게 끝나지 않음(수집기가 멈춘 듯)"
        elif r.status == "pending" and r.requested_at and now - datetime.fromisoformat(r.requested_at) > timedelta(minutes=PENDING_MINUTES):
            r.status, r.finished_at, r.message = "failed", _iso(now), f"{PENDING_MINUTES}분 동안 수집기가 가져가지 않아 취소"


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"모르는 수집 종류: {kind}")
    return kind


class RequestIn(BaseModel):
    kind: str = "shape"


@router.post("/requests")  # 화면 버튼 — open(다른 UI 액션처럼). 실제 수집은 러너 토큰을 가진 수집기만
def request_collect(body: RequestIn, db: Session = Depends(get_db)) -> dict:
    kind = _kind(body.kind)
    now = _now()
    _expire(db, now)
    if _alive(db, now) is None:  # 아무도 안 가져갈 요청을 쌓지 않음(화면 버튼도 이때는 꺼져 있음)
        db.commit()
        raise HTTPException(status_code=409, detail="수집기가 꺼져 있어요 — 수집기를 켠 뒤 다시 눌러 주세요")
    open_ = (
        db.query(CollectRequest)
        .filter(CollectRequest.kind == kind, CollectRequest.status.in_(("pending", "running")))
        .order_by(CollectRequest.id.desc())
        .first()
    )
    if open_:  # 이미 기다리거나 도는 중이면 새로 안 만듦(버튼 연타)
        return {**_out(open_), "reused": True}
    r = CollectRequest(kind=kind, status="pending", requested_at=_iso(now))
    db.add(r)
    record(db, "collect.request", actor="user", target_type="collect", target_id=kind)
    db.commit()
    db.refresh(r)
    return {**_out(r), "reused": False}


@router.get("/status")
def collect_status(kind: str = "shape", db: Session = Depends(get_db)) -> dict:
    """가장 최근 요청 + 수집기가 켜져 있나(마지막 확인 시각). 오래 멈춘 요청은 여기서도 닫음."""
    kind = _kind(kind)
    now = _now()
    _expire(db, now)
    db.commit()
    last = db.query(CollectRequest).filter(CollectRequest.kind == kind).order_by(CollectRequest.id.desc()).first()
    c = db.query(Collector).order_by(Collector.last_seen_at.desc()).first()
    collector = None
    if c:
        collector = {"name": c.name, "mode": c.mode, "last_seen_at": c.last_seen_at, "alive": _alive(db, now) is not None}
    return {"request": _out(last), "collector": collector}


class ClaimIn(BaseModel):
    kind: str = "shape"
    collector: str = "collector"
    mode: str | None = None


@router.post("/claim", dependencies=[Depends(require_runner)])
def claim(body: ClaimIn, db: Session = Depends(get_db)) -> dict:
    """수집기가 몇 초마다 부름 — 켜져 있다는 표시를 남기고, 기다리는 요청이 있으면 하나 가져감(→ 수집 중)."""
    kind = _kind(body.kind)
    now = _now()
    c = db.query(Collector).filter(Collector.name == body.collector).first() or Collector(name=body.collector)
    c.mode, c.last_seen_at = body.mode, _iso(now)
    db.add(c)
    _expire(db, now)
    r = (
        db.query(CollectRequest)
        .filter(CollectRequest.kind == kind, CollectRequest.status == "pending")
        .order_by(CollectRequest.id)
        .first()
    )
    if r:
        r.status, r.started_at, r.collector = "running", _iso(now), body.collector
    db.commit()
    return {"request": _out(r)}


class FinishIn(BaseModel):
    ok: bool
    message: str | None = None


@router.post("/requests/{request_id}/finish", dependencies=[Depends(require_runner)])
def finish(request_id: int, body: FinishIn, db: Session = Depends(get_db)) -> dict:
    r = db.get(CollectRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="요청 없음")
    r.status = "done" if body.ok else "failed"
    r.finished_at = _iso(_now())
    r.message = (body.message or "")[:500] or None
    record(db, "collect.done" if body.ok else "collect.failed", target_type="collect", target_id=r.kind, detail=r.message)
    db.commit()
    return _out(r)
