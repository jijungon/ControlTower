"""감사 로그 기록 헬퍼 — 러너/사용자 액션을 audit_logs 에 남긴다.

record() 는 세션에 add 만 한다(커밋은 호출한 엔드포인트가 함께 처리) → 같은 트랜잭션.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    actor: str = "runner",
    target_type: str | None = None,
    target_id: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    )
