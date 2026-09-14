"""작업이력 / 감사 로그 조회 (읽기 전용, 최신순)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]
