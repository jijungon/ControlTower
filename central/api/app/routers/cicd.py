"""CI/CD 현황 (Phase 5) — 서비스별 파이프라인 상태.

소스 무관 인제스트: 러너(GitLab 피더)나 웹훅이 상태를 업로드 → GET /api/cicd 로 표시.
targets(서비스↔GitLab 프로젝트)로 아직 상태가 없는 서비스도 목록에 노출.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import CicdTarget, PipelineStatus

router = APIRouter(prefix="/api/cicd", tags=["cicd"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── targets (서비스 ↔ GitLab 프로젝트) ───────────────────────────────
class TargetIn(BaseModel):
    service: str
    project: str


@router.get("/targets")
def list_targets(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(CicdTarget).order_by(CicdTarget.service).all()
    return [{"service": t.service, "project": t.project} for t in rows]


@router.post("/targets")  # 대상 등록은 UI(설정) 액션 — open. 상태 업로드(/status)만 러너 토큰.
def add_target(body: TargetIn, db: Session = Depends(get_db)) -> dict:
    row = db.query(CicdTarget).filter(CicdTarget.service == body.service).first()
    if row is None:
        row = CicdTarget(service=body.service)
        db.add(row)
    row.project = body.project
    db.commit()
    return {"ok": True, "service": body.service}


# ── status (피더 업로드) ─────────────────────────────────────────────
class StatusIn(BaseModel):
    service: str
    has_cicd: bool = False
    status: str | None = None
    ref: str | None = None
    sha: str | None = None
    web_url: str | None = None


class StatusBatch(BaseModel):
    statuses: list[StatusIn]


@router.post("/status", dependencies=[Depends(require_runner)])
def upload_status(batch: StatusBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    for s in batch.statuses:
        row = db.query(PipelineStatus).filter(PipelineStatus.service == s.service).first()
        if row is None:
            row = PipelineStatus(service=s.service)
            db.add(row)
        row.has_cicd = 1 if s.has_cicd else 0
        row.status = s.status
        row.ref = s.ref
        row.sha = s.sha
        row.web_url = s.web_url
        row.collected_at = now
    record(db, "cicd.collect", target_type="cicd", detail=f"{len(batch.statuses)}개")
    db.commit()
    return {"accepted": len(batch.statuses)}


# ── 현황 매트릭스 ────────────────────────────────────────────────────
@router.get("")
def cicd_matrix(db: Session = Depends(get_db)) -> list[dict]:
    targets = {t.service: t.project for t in db.query(CicdTarget).all()}
    statuses = {s.service: s for s in db.query(PipelineStatus).all()}
    services = sorted(set(targets) | set(statuses))
    out: list[dict] = []
    for svc in services:
        s = statuses.get(svc)
        out.append(
            {
                "service": svc,
                "project": targets.get(svc),
                "has_cicd": bool(s.has_cicd) if s else False,
                "status": s.status if s else None,
                "ref": s.ref if s else None,
                "sha": s.sha if s else None,
                "web_url": s.web_url if s else None,
                "collected_at": s.collected_at if s else None,
            }
        )
    return out
