"""conf 관리 (Phase 1) — 대상 경로·기준본·스냅샷·드리프트.

흐름: targets(관리 경로) → 러너가 서버에서 읽어 snapshots 업로드 →
      baseline(기준본)과 sha256 비교 → GET /api/conf 로 드리프트 매트릭스.
"""
from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import ConfApplyIntent, ConfBaseline, ConfSnapshot, ConfTarget, Server

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
    record(db, "conf.collect", target_type="conf", detail=f"{len(batch.snapshots)}건")
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
    record(db, "conf.adopt", target_type="conf", target_id=body.path)
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


# ── 적용(배포): plan → approve → apply (러너는 approved 만 적용) ──────
def _unified(current: str | None, target: str | None) -> str:
    return "".join(
        difflib.unified_diff(
            (current or "").splitlines(keepends=True),
            (target or "").splitlines(keepends=True),
            fromfile="current(server)",
            tofile="baseline(target)",
        )
    )


def _intent_dump(it: ConfApplyIntent, hostname: str) -> dict:
    return {
        "id": it.id,
        "server_id": it.server_id,
        "hostname": hostname,
        "path": it.path,
        "status": it.status,
        "from_sha": it.from_sha,
        "to_sha": it.to_sha,
        "diff": it.diff,
        "requested_by": it.requested_by,
        "approved_by": it.approved_by,
        "backup_path": it.backup_path,
        "error": it.error,
        "created_at": it.created_at,
        "approved_at": it.approved_at,
        "applied_at": it.applied_at,
    }


class PlanIn(BaseModel):
    server_id: int
    path: str


@router.post("/apply/plan")
def apply_plan(body: PlanIn, db: Session = Depends(get_db)) -> dict:
    """드리프트난 (server, path)에 대해 '기준본으로 바꾸겠다'는 의도 생성(pending). 서버는 안 건드림."""
    snap = (
        db.query(ConfSnapshot)
        .filter(ConfSnapshot.server_id == body.server_id, ConfSnapshot.path == body.path)
        .first()
    )
    if snap is None or snap.content is None:
        raise HTTPException(status_code=400, detail="실제본(스냅샷)이 없습니다")
    base = db.query(ConfBaseline).filter(ConfBaseline.path == body.path).first()
    if base is None:
        raise HTTPException(status_code=400, detail="기준본이 없습니다")
    if snap.sha256 == base.sha256:
        raise HTTPException(status_code=400, detail="드리프트가 아닙니다(변경 없음)")

    intent = ConfApplyIntent(
        server_id=body.server_id,
        path=body.path,
        from_sha=snap.sha256,
        to_sha=base.sha256,
        diff=_unified(snap.content, base.content),
        status="pending",
        requested_by="ui",
        created_at=_now(),
    )
    db.add(intent)
    record(db, "conf.apply_plan", target_type="conf", target_id=body.path)
    db.commit()
    srv = db.get(Server, body.server_id)
    return _intent_dump(intent, srv.hostname if srv else str(body.server_id))


@router.post("/apply/{intent_id}/approve")
def apply_approve(intent_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ConfApplyIntent, intent_id)
    if it is None:
        raise HTTPException(status_code=404, detail="의도를 찾을 수 없음")
    if it.status != "pending":
        raise HTTPException(status_code=409, detail=f"pending 상태가 아님({it.status})")
    it.status = "approved"
    it.approved_by = "ui"
    it.approved_at = _now()
    record(db, "conf.apply_approve", target_type="conf", target_id=it.path)
    db.commit()
    srv = db.get(Server, it.server_id)
    return _intent_dump(it, srv.hostname if srv else str(it.server_id))


@router.post("/apply/{intent_id}/cancel")
def apply_cancel(intent_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ConfApplyIntent, intent_id)
    if it is None:
        raise HTTPException(status_code=404, detail="의도를 찾을 수 없음")
    if it.status not in ("pending", "approved"):
        raise HTTPException(status_code=409, detail=f"취소할 수 없는 상태({it.status})")
    it.status = "canceled"
    record(db, "conf.apply_cancel", target_type="conf", target_id=it.path)
    db.commit()
    srv = db.get(Server, it.server_id)
    return _intent_dump(it, srv.hostname if srv else str(it.server_id))


@router.get("/apply")
def apply_list(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    servers = {s.id: s for s in db.query(Server).all()}
    q = db.query(ConfApplyIntent)
    if status:
        q = q.filter(ConfApplyIntent.status == status)
    rows = q.order_by(ConfApplyIntent.id.desc()).all()
    return [_intent_dump(it, servers[it.server_id].hostname if it.server_id in servers else str(it.server_id)) for it in rows]


@router.get("/apply/{intent_id}/content", dependencies=[Depends(require_runner)])
def apply_content(intent_id: int, db: Session = Depends(get_db)) -> dict:
    """러너가 적용 직전 호출 — 서버에 쓸 기준본 내용. approved 만, 승인 후 기준본이 바뀌었으면 거부."""
    it = db.get(ConfApplyIntent, intent_id)
    if it is None:
        raise HTTPException(status_code=404, detail="의도를 찾을 수 없음")
    if it.status != "approved":
        raise HTTPException(status_code=409, detail=f"approved 상태가 아님({it.status})")
    base = db.query(ConfBaseline).filter(ConfBaseline.path == it.path).first()
    if base is None or base.sha256 != it.to_sha:
        raise HTTPException(status_code=409, detail="기준본이 승인 후 변경됨 — 재계획 필요")
    return {"path": it.path, "content": base.content, "to_sha": it.to_sha}


class ApplyResultIn(BaseModel):
    status: str                  # applied | failed
    backup_path: str | None = None
    error: str | None = None


@router.post("/apply/{intent_id}/result", dependencies=[Depends(require_runner)])
def apply_result(intent_id: int, body: ApplyResultIn, db: Session = Depends(get_db)) -> dict:
    """러너가 실제 적용(PR-B) 후 결과 보고. approved 만 적용 가능."""
    it = db.get(ConfApplyIntent, intent_id)
    if it is None:
        raise HTTPException(status_code=404, detail="의도를 찾을 수 없음")
    if it.status != "approved":
        raise HTTPException(status_code=409, detail=f"approved 상태가 아님({it.status})")
    if body.status not in ("applied", "failed"):
        raise HTTPException(status_code=400, detail="status 는 applied|failed")
    it.status = body.status
    it.backup_path = body.backup_path
    it.error = body.error
    it.applied_at = _now()
    record(db, "conf.apply_result", target_type="conf", target_id=it.path, detail=body.status)
    db.commit()
    srv = db.get(Server, it.server_id)
    return _intent_dump(it, srv.hostname if srv else str(it.server_id))


@router.post("/apply/{intent_id}/rollback", dependencies=[Depends(require_runner)])
def apply_rollback(intent_id: int, db: Session = Depends(get_db)) -> dict:
    """러너가 백업본으로 되돌린 뒤 보고. applied 만 롤백 가능."""
    it = db.get(ConfApplyIntent, intent_id)
    if it is None:
        raise HTTPException(status_code=404, detail="의도를 찾을 수 없음")
    if it.status != "applied":
        raise HTTPException(status_code=409, detail=f"applied 상태가 아님({it.status})")
    it.status = "rolled_back"
    record(db, "conf.apply_rollback", target_type="conf", target_id=it.path)
    db.commit()
    srv = db.get(Server, it.server_id)
    return _intent_dump(it, srv.hostname if srv else str(it.server_id))
