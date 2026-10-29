"""업데이트 관리 (Phase 2) — 서버별 대기 중인 OS 패치(apt) 수집.

흐름: 러너가 서버에서 `apt list --upgradable` 을 파싱해 snapshots 업로드 →
      GET /api/updates 로 서버별 대기/보안 개수 + 패키지 목록(드릴다운).
수집기 도장 길(#58)에서 금고 도장이 거절한 것은 error 가 BLOCKED 로 시작한다 → blocked=True ·
  '이 길로는 못 읽음'(오류도 정상도 아님). 까닭은 blocked_reason, error 는 빈 글.
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
from ..models import Server, UpdateSnapshot

router = APIRouter(prefix="/api/updates", tags=["updates"])
# runner/conn.py 의 BLOCKED 와 같은 글 — 도장이 거절함(rc 126 + idp-collect:) · 박힌 규칙 밖이라 안 보냄
BLOCKED = "이 길(도장)로는 못 읽음 — "


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
    record(db, "updates.collect", target_type="updates", detail=f"{len(batch.snapshots)}대")
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
        blocked = (snap.error or "").startswith(BLOCKED)
        out.append(
            {
                "server_id": snap.server_id,
                "hostname": srv.hostname if srv else str(snap.server_id),
                "pending": len(pkgs),
                "security": sum(1 for p in pkgs if p.get("security")),
                "packages": pkgs,
                "error": "" if blocked else (snap.error or ""),
                "blocked": blocked,
                "blocked_reason": snap.error[len(BLOCKED):] if blocked else "",
                "collected_at": snap.collected_at,
            }
        )
    out.sort(key=lambda r: r["hostname"])
    return out
