"""버전 관리 (Phase 3) — 빌드 서버 툴체인 버전(node/java/docker 등) 수집.

흐름: 러너가 서버에서 `node --version` 등을 실행·파싱해 snapshots 업로드 →
      GET /api/versions 로 서버 × 툴 매트릭스.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import Server, ToolSnapshot

router = APIRouter(prefix="/api/versions", tags=["versions"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SnapshotIn(BaseModel):
    server_id: int
    tool: str
    version: str | None = None


class SnapshotBatch(BaseModel):
    snapshots: list[SnapshotIn]


@router.post("/snapshots", dependencies=[Depends(require_runner)])
def upload_snapshots(batch: SnapshotBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    for s in batch.snapshots:
        row = (
            db.query(ToolSnapshot)
            .filter(ToolSnapshot.server_id == s.server_id, ToolSnapshot.tool == s.tool)
            .first()
        )
        if row is None:
            row = ToolSnapshot(server_id=s.server_id, tool=s.tool)
            db.add(row)
        row.version = s.version
        row.collected_at = now
    record(db, "versions.collect", target_type="versions", detail=f"{len(batch.snapshots)}건")
    db.commit()
    return {"accepted": len(batch.snapshots)}


@router.get("")
def versions_matrix(db: Session = Depends(get_db)) -> list[dict]:
    servers = {s.id: s for s in db.query(Server).all()}
    by_server: dict[int, dict] = {}
    for snap in db.query(ToolSnapshot).all():
        entry = by_server.setdefault(
            snap.server_id,
            {
                "server_id": snap.server_id,
                "hostname": servers[snap.server_id].hostname if snap.server_id in servers else str(snap.server_id),
                "tools": {},
                "collected_at": snap.collected_at,
            },
        )
        if snap.version:
            entry["tools"][snap.tool] = snap.version
        if snap.collected_at and (entry["collected_at"] is None or snap.collected_at > entry["collected_at"]):
            entry["collected_at"] = snap.collected_at
    out = list(by_server.values())
    out.sort(key=lambda r: r["hostname"])
    return out
