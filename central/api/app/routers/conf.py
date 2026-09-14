"""conf 관리 (Phase 1) — 대상 경로·기준본·스냅샷·드리프트.

흐름: targets(관리 경로) → 러너가 서버에서 읽어 snapshots 업로드 →
      baseline(기준본)과 sha256 비교 → GET /api/conf 로 드리프트 매트릭스.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..db import get_db
from ..models import ConfBaseline, ConfSnapshot, ConfTarget, Server

router = APIRouter(prefix="/api/conf", tags=["conf"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── targets ──────────────────────────────────────────────────────────
class TargetIn(BaseModel):
    path: str


@router.get("/targets")
def list_targets(db: Session = Depends(get_db)) -> list[str]:
    return [t.path for t in db.query(ConfTarget).order_by(ConfTarget.path).all()]


@router.post("/targets", dependencies=[Depends(require_runner)])
def add_target(body: TargetIn, db: Session = Depends(get_db)) -> dict:
    if not db.query(ConfTarget).filter(ConfTarget.path == body.path).first():
        db.add(ConfTarget(path=body.path))
        db.commit()
    return {"ok": True, "path": body.path}


# ── snapshots (러너 업로드) ──────────────────────────────────────────
class SnapshotIn(BaseModel):
    server_id: int
    path: str
    content: str | None = None
    error: str | None = None


class SnapshotBatch(BaseModel):
    snapshots: list[SnapshotIn]


@router.post("/snapshots", dependencies=[Depends(require_runner)])
def upload_snapshots(batch: SnapshotBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    for s in batch.snapshots:
        row = (
            db.query(ConfSnapshot)
            .filter(ConfSnapshot.server_id == s.server_id, ConfSnapshot.path == s.path)
            .first()
        )
        if row is None:
            row = ConfSnapshot(server_id=s.server_id, path=s.path)
            db.add(row)
        row.content = s.content
        row.sha256 = _sha(s.content) if s.content is not None else None
        row.error = s.error
        row.collected_at = now
    db.commit()
    return {"accepted": len(batch.snapshots)}


# ── baseline 채택(adopt) ─────────────────────────────────────────────
class AdoptIn(BaseModel):
    path: str
    server_id: int


@router.post("/baselines/adopt", dependencies=[Depends(require_runner)])
def adopt_baseline(body: AdoptIn, db: Session = Depends(get_db)) -> dict:
    snap = (
        db.query(ConfSnapshot)
        .filter(ConfSnapshot.server_id == body.server_id, ConfSnapshot.path == body.path)
        .first()
    )
    if snap is None or snap.content is None:
        raise HTTPException(status_code=404, detail="채택할 스냅샷이 없음")
    base = db.query(ConfBaseline).filter(ConfBaseline.path == body.path).first()
    if base is None:
        base = ConfBaseline(path=body.path, content="", sha256="")
        db.add(base)
    base.content = snap.content
    base.sha256 = snap.sha256
    base.updated_at = _now()
    db.commit()
    return {"ok": True, "path": body.path, "sha256": snap.sha256}


# ── 드리프트 매트릭스 ────────────────────────────────────────────────
@router.get("")
def conf_matrix(db: Session = Depends(get_db)) -> list[dict]:
    baselines = {b.path: b for b in db.query(ConfBaseline).all()}
    servers = {s.id: s for s in db.query(Server).all()}
    out: list[dict] = []
    for snap in db.query(ConfSnapshot).all():
        base = baselines.get(snap.path)
        if snap.error:
            status = "error"
        elif base is None:
            status = "no_baseline"
        elif base.sha256 == snap.sha256:
            status = "synced"
        else:
            status = "drift"
        srv = servers.get(snap.server_id)
        out.append(
            {
                "server_id": snap.server_id,
                "hostname": srv.hostname if srv else str(snap.server_id),
                "path": snap.path,
                "status": status,
                "detail": snap.error or "",
                "collected_at": snap.collected_at,
            }
        )
    out.sort(key=lambda r: (r["hostname"], r["path"]))
    return out
