"""다시 수집 — 화면 버튼(수동)이나 수집기의 매일 정해 둔 시각(자동)이 요청을 남기고, 수집기(agent)가 가져가 처리한다.

중앙은 키·토큰이 없다(조회 전용). 그래서 수집을 직접 하지 않고 요청만 저장한다.
수집기는 ControlTower 와 같은 서버(또는 PC)에서 돌며 몇 초마다 /claim 으로 요청을 확인 → GitLab 을 다시 읽어 올림 → /finish.
GET /servers — 수집기가 도장 길(#58)로 읽을 서버의 주소. 수집기 신분(ct-collector)은 금고 목록을 못 읽어서
  중앙(ct-inventory)이 대신 찾아 준다 — 수집기가 이름으로 물은 서버만, 이름 · 주소만(사람 · 이메일은 안 줌).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..inventory_source import ENVS, InventoryError, fetch_inventory
from ..models import Collector, CollectRequest

router = APIRouter(prefix="/api/collect", tags=["collect"])

KINDS = {"shape"}  # shape = 빌드·배포 + config (runner shape)
ALIVE_SECONDS = 60  # 이 안에 확인했으면 '수집기 켜짐'
STALE_MINUTES = 15  # 수집 중으로 이만큼 지나면 수집기가 죽은 것 → 실패로
PENDING_MINUTES = 10  # 요청됨으로 이만큼 아무도 안 가져가면 취소(수집기가 꺼져 있던 것)
MAX_PICKS = 50  # /servers 에 한 번에 물을 수 있는 이름 수


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
        "trigger": r.trigger or "user",
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
    r = CollectRequest(kind=kind, status="pending", requested_at=_iso(now), trigger="user")
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
        collector = {
            "name": c.name, "mode": c.mode, "schedule": c.schedule, "last_seen_at": c.last_seen_at,
            "alive": _alive(db, now) is not None,
        }
    return {"request": _out(last), "collector": collector}


class ClaimIn(BaseModel):
    kind: str = "shape"
    collector: str = "collector"
    mode: str | None = None
    schedule: str | None = None  # 자동 수집 시각(화면 안내용)


@router.post("/claim", dependencies=[Depends(require_runner)])
def claim(body: ClaimIn, db: Session = Depends(get_db)) -> dict:
    """수집기가 몇 초마다 부름 — 켜져 있다는 표시를 남기고, 기다리는 요청이 있으면 하나 가져감(→ 수집 중)."""
    kind = _kind(body.kind)
    now = _now()
    c = db.query(Collector).filter(Collector.name == body.collector).first() or Collector(name=body.collector)
    c.mode, c.schedule, c.last_seen_at = body.mode, body.schedule, _iso(now)
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


class AutoIn(BaseModel):
    kind: str = "shape"
    since: str  # 이 시각(ISO, 오늘의 자동 수집 시각) 뒤로 끝난 수집이 없으면 자동 요청을 만든다


@router.post("/auto", dependencies=[Depends(require_runner)])
def auto_request(body: AutoIn, db: Session = Depends(get_db)) -> dict:
    """수집기가 매일 정해 둔 시각이 지나면 부름 — 그 뒤로 끝난 수집(버튼 포함)이 없고 기다리는 요청도 없으면 자동 요청을 하나 만듦.
    수집기가 그 시각에 꺼져 있었다가 늦게 켜져도 하루 한 번은 돈다. 판단은 DB 로 해서 수집기를 다시 켜도 두 번 돌지 않음."""
    kind = _kind(body.kind)
    now = _now()
    _expire(db, now)
    since = datetime.fromisoformat(body.since)
    done = (
        db.query(CollectRequest)
        .filter(CollectRequest.kind == kind, CollectRequest.status == "done", CollectRequest.finished_at.isnot(None))
        .all()
    )
    if any(datetime.fromisoformat(r.finished_at) >= since for r in done):
        db.commit()
        return {"created": False, "reason": "오늘 이미 수집함", "request": None}
    open_ = db.query(CollectRequest).filter(CollectRequest.kind == kind, CollectRequest.status.in_(("pending", "running"))).first()
    if open_:
        db.commit()
        return {"created": False, "reason": "이미 기다리거나 도는 수집이 있음", "request": _out(open_)}
    r = CollectRequest(kind=kind, status="pending", requested_at=_iso(now), trigger="auto")
    db.add(r)
    record(db, "collect.request", actor="collector", target_type="collect", target_id=kind, detail="자동(매일 정해 둔 시각)")
    db.commit()
    db.refresh(r)
    return {"created": True, "reason": None, "request": _out(r)}


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


@router.get("/servers", dependencies=[Depends(require_runner)])
def collect_servers(pick: list[str] = Query(default=[])) -> dict:
    """pick = <환경>/<서비스>/<서버> 이름들 → 금고 목록(inventory/<환경>/<서비스> 의 servers)에서 찾은 주소.
    찾은 것만 servers 에, 못 찾은 이름은 missing 에(추측하지 않음). 이름을 안 주면 아무것도 안 준다(목록 통째로 안 내줌).
    금고 연결이 꺼져 있으면 state=off, 못 읽으면 state=error(까닭) — 빈 목록으로 보이지 않게."""
    picks = list(dict.fromkeys(p.strip() for p in pick if p.strip()))[:MAX_PICKS]
    try:
        inv = fetch_inventory()
    except InventoryError as exc:
        if str(exc) == "off":
            return {"state": "off", "servers": [], "missing": picks}
        return {"state": "error", "error": str(exc), "servers": [], "missing": picks}
    servers, missing = [], []
    for p in picks:
        env, _, rest = p.partition("/")
        service, _, name = rest.partition("/")
        entry = (inv.get(env) or {}).get(service) if env in ENVS else None
        addr = ((entry or {}).get("servers") or {}).get(name) if isinstance(entry, dict) else None
        if name and "/" not in name and isinstance(addr, str) and addr:
            servers.append({"env": env, "service": service, "name": name, "addr": addr})
        else:
            missing.append(p)
    return {"state": "ok", "servers": servers, "missing": missing}
