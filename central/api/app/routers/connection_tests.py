"""연결 테스트 결과 수신 — 러너가 SSH 연결 테스트 후 업로드. 서버 status 갱신."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import ConnectionTest, Server

router = APIRouter(prefix="/api", tags=["connection-tests"])


class TestResult(BaseModel):
    server_id: int
    ok: bool
    latency_ms: int | None = None
    error: str | None = None
    needs_2fa: bool | None = None   # 접속 점검(probe) 결과: 추가 인증 필요 여부


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
            if r.needs_2fa is not None:
                srv.needs_2fa = 1 if r.needs_2fa else 0
    ok = sum(1 for r in batch.results if r.ok)
    record(db, "conn.test", target_type="servers", detail=f"{ok}/{len(batch.results)} OK")
    db.commit()
    return {"accepted": len(batch.results)}
