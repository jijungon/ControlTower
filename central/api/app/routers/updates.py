"""업데이트 관리 (Phase 2) — 서버별 대기 중인 OS 패치(apt) 수집.

흐름: 러너가 서버에서 `apt list --upgradable` 을 파싱해 snapshots 업로드 →
      GET /api/updates 로 서버별 대기/보안 개수 + 패키지 목록(드릴다운).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..db import get_db
from ..models import Server, UpdateSnapshot

router = APIRouter(prefix="/api/updates", tags=["updates"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── snapshots (러너 업로드) ──────────────────────────────────────────
class SnapshotIn(BaseModel):
    server_id: int
    packages: list[dict[str, Any]] | None = None  # [{name,from,to,security}] · 수집 실패 시 None
    error: str | None = None


class SnapshotBatch(BaseModel):
    snapshots: list[SnapshotIn]


@router.post("/snapshots", dependencies=[Depends(require_runner)])
def upload_snapshots(batch: SnapshotBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    for s in batch.snapshots:
        row = db.query(UpdateSnapshot).filter(UpdateSnapshot.server_id == s.server_id).first()
        if row is None:
            row = UpdateSnapshot(server_id=s.server_id)
            db.add(row)
        row.packages = json.dumps(s.packages, ensure_ascii=False) if s.packages is not None else None
        row.error = s.error
        row.collected_at = now
    db.commit()
    return {"accepted": len(batch.snapshots)}


# ── 서버별 업데이트 현황 ─────────────────────────────────────────────
@router.get("")
def updates_matrix(db: Session = Depends(get_db)) -> list[dict]:
    servers = {s.id: s for s in db.query(Server).all()}
    out: list[dict] = []
    for snap in db.query(UpdateSnapshot).all():
        pkgs: list[dict] = json.loads(snap.packages) if snap.packages else []
        srv = servers.get(snap.server_id)
        out.append(
            {
                "server_id": snap.server_id,
                "hostname": srv.hostname if srv else str(snap.server_id),
                "pending": len(pkgs),
                "security": sum(1 for p in pkgs if p.get("security")),
                "packages": pkgs,
                "error": snap.error or "",
                "collected_at": snap.collected_at,
            }
        )
    out.sort(key=lambda r: r["hostname"])
    return out
