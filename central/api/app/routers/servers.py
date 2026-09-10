"""서버 인벤토리 — 러너가 수집/배포 대상 목록을 받아간다."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Server

router = APIRouter(prefix="/api", tags=["servers"])


@router.get("/servers")
def list_servers(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Server).all()
    return [
        {
            "id": s.id,
            "hostname": s.hostname,
            "ssh_port": s.ssh_port,
            "ssh_user": s.ssh_user,
            "role": s.role,
            "access_method": s.access_method,
            "gateway_id": s.gateway_id,
            "credential_alias": s.credential_alias,
            "status": s.status,
        }
        for s in rows
    ]

    # TODO(Phase 0): 서버 등록/수정(POST/PATCH), ~/.ssh/config 임포트 엔드포인트
