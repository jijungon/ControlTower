"""서버 인벤토리 — 목록 조회(GET) + 러너의 ~/.ssh/config 임포트(POST)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_runner
from ..db import get_db
from ..models import Server

router = APIRouter(prefix="/api", tags=["servers"])


class ImportServer(BaseModel):
    hostname: str                        # ssh config Host 별칭 (ssh <hostname> 로 접속)
    ip: str | None = None                # HostName
    ssh_user: str = ""
    ssh_port: int = 22
    gateway_alias: str | None = None     # ProxyJump
    credential_alias: str | None = None  # IdentityFile basename
    access_control: str | None = None    # dbsafe·ncloud 등


class ImportPayload(BaseModel):
    servers: list[ImportServer]


def _dump(s: Server) -> dict:
    return {
        "id": s.id,
        "hostname": s.hostname,
        "ip": s.ip,
        "ssh_port": s.ssh_port,
        "ssh_user": s.ssh_user,
        "role": s.role,
        "access_method": s.access_method,
        "gateway_id": s.gateway_id,
        "credential_alias": s.credential_alias,
        "access_control": s.access_control,
        "status": s.status,
        "last_checked_at": s.last_checked_at,
    }


@router.get("/servers")
def list_servers(db: Session = Depends(get_db)) -> list[dict]:
    return [_dump(s) for s in db.query(Server).order_by(Server.hostname).all()]


@router.post("/servers/import", dependencies=[Depends(require_runner)])
def import_servers(payload: ImportPayload, db: Session = Depends(get_db)) -> dict:
    """hostname(별칭) 기준 upsert. 러너가 파싱한 ssh config 를 받아 인벤토리에 반영."""
    created = 0
    for item in payload.servers:
        row = db.query(Server).filter(Server.hostname == item.hostname).first()
        if row is None:
            row = Server(hostname=item.hostname, ssh_user=item.ssh_user or "unknown")
            db.add(row)
            created += 1
        row.ip = item.ip
        row.ssh_user = item.ssh_user or row.ssh_user
        row.ssh_port = item.ssh_port
        row.credential_alias = item.credential_alias
        row.access_control = item.access_control
        row.access_method = "via_gateway" if item.gateway_alias else "direct"
    db.flush()

    # 2차 패스: ProxyJump 별칭 → gateway_id 연결 + 그 gw 는 role=gateway 로 표시
    by_alias = {s.hostname: s for s in db.query(Server).all()}
    for item in payload.servers:
        if not item.gateway_alias:
            continue
        gw = by_alias.get(item.gateway_alias)
        target = by_alias.get(item.hostname)
        if gw is not None and target is not None:
            gw.role = "gateway"
            target.gateway_id = gw.id

    db.commit()
    return {"imported_new": created, "total": len(payload.servers)}
