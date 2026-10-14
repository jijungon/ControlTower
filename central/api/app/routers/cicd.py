"""CI/CD 현황 (Phase 5) — 서비스별 파이프라인 상태.

소스 무관 인제스트: 러너(GitLab 피더)나 웹훅이 상태를 업로드 → GET /api/cicd 로 표시.
targets(서비스↔GitLab 프로젝트)로 아직 상태가 없는 서비스도 목록에 노출.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import CicdTarget, ConfigItem, PipelineStatus, ServiceShape

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


# ── 서비스 비교표 (shape) ────────────────────────────────────────────
class ShapeIn(BaseModel):
    service: str
    group: str | None = None
    data: dict[str, Any] = {}
    env_hash: str | None = None  # variables 해시(값은 받지 않음)


class ShapeBatch(BaseModel):
    shapes: list[ShapeIn]
    replace: bool = False  # True = 이번에 안 온 서비스는 표에서 내림(대상 파일이 기준)


@router.post("/shape", dependencies=[Depends(require_runner)])
def upload_shapes(batch: ShapeBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    seen = set()
    for s in batch.shapes:
        seen.add(s.service)
        row = db.query(ServiceShape).filter(ServiceShape.service == s.service).first()
        if row is None:
            row = ServiceShape(service=s.service)
            db.add(row)
        elif s.env_hash and row.env_hash and s.env_hash != row.env_hash:
            row.env_changed_at = now  # 첫 수집은 '언제 바뀌었는지' 모르므로 비워 둠
        row.group_name = s.group
        row.data = json.dumps(s.data, ensure_ascii=False)
        row.env_hash = s.env_hash
        row.collected_at = now
    removed = 0
    if batch.replace:
        for row in db.query(ServiceShape).all():
            if row.service not in seen:
                db.delete(row)
                removed += 1
    record(db, "cicd.shape", target_type="cicd", detail=f"{len(batch.shapes)}개" + (f" · 내림 {removed}" if removed else ""))
    db.commit()
    return {"accepted": len(batch.shapes), "removed": removed}


@router.get("/shape")
def list_shapes(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ServiceShape).order_by(ServiceShape.group_name, ServiceShape.service).all()
    out: list[dict] = []
    for r in rows:
        try:
            data = json.loads(r.data or "{}")
        except ValueError:
            data = {}
        out.append(
            {
                **data,
                "service": r.service,
                "group": r.group_name,
                "env_changed_at": r.env_changed_at,
                "collected_at": r.collected_at,
            }
        )
    return out


# ── center config repo (폴더별) ──────────────────────────────────────
class ConfigItemIn(BaseModel):
    path: str
    data: dict[str, Any] = {}


class ConfigBatch(BaseModel):
    items: list[ConfigItemIn]
    replace: bool = False  # True = 이번에 안 온 폴더는 표에서 내림(repo 에서 지워진 폴더)


@router.post("/config", dependencies=[Depends(require_runner)])
def upload_config(batch: ConfigBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    seen = {i.path for i in batch.items}
    for i in batch.items:
        row = db.query(ConfigItem).filter(ConfigItem.path == i.path).first()
        if row is None:
            row = ConfigItem(path=i.path)
            db.add(row)
        row.data = json.dumps(i.data, ensure_ascii=False)
        row.collected_at = now
    removed = 0
    if batch.replace:
        for row in db.query(ConfigItem).all():
            if row.path not in seen:
                db.delete(row)
                removed += 1
    record(db, "cicd.config", target_type="cicd", detail=f"{len(batch.items)}개" + (f" · 내림 {removed}" if removed else ""))
    db.commit()
    return {"accepted": len(batch.items), "removed": removed}


@router.get("/config")
def list_config(db: Session = Depends(get_db)) -> list[dict]:
    out: list[dict] = []
    for r in db.query(ConfigItem).order_by(ConfigItem.path).all():
        try:
            data = json.loads(r.data or "{}")
        except ValueError:
            data = {}
        out.append({**data, "path": r.path, "collected_at": r.collected_at})
    return out


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
