"""연결 테스트 결과 수신 — 러너가 SSH 연결 테스트 후 업로드. 서버 status 갱신."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..db import get_db
from ..models import ConnectionTest, Server

router = APIRouter(prefix="/api", tags=["connection-tests"])


class TestResult(BaseModel):
    server_id: int
    ok: bool
    latency_ms: int | None = None
    error: str | None = None


class TestBatch(BaseModel):
    results: list[TestResult]


@router.post("/connection-tests", dependencies=[Depends(require_runner)])
def post_connection_tests(batch: TestBatch, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in batch.results:
        db.add(
            ConnectionTest(
                server_id=r.server_id,
                ok=1 if r.ok else 0,
                latency_ms=r.latency_ms,
                error=r.error,
            )
        )
        srv = db.get(Server, r.server_id)
        if srv is not None:
            srv.status = "online" if r.ok else "offline"
            srv.last_checked_at = now
    db.commit()
    return {"accepted": len(batch.results)}
