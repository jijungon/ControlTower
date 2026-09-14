"""서버 인벤토리 — 목록 조회(GET) + 러너의 ~/.ssh/config 임포트(POST)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import Server, ServerGroup

router = APIRouter(prefix="/api", tags=["servers"])


def _tags_list(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


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


def _dump(s: Server, groups: dict[int, str]) -> dict:
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
        "group_id": s.group_id,
        "group": groups.get(s.group_id) if s.group_id else None,
        "tags": _tags_list(s.tags),
        "status": s.status,
        "last_checked_at": s.last_checked_at,
    }


@router.get("/servers")
def list_servers(db: Session = Depends(get_db)) -> list[dict]:
    groups = {g.id: g.name for g in db.query(ServerGroup).all()}
    return [_dump(s, groups) for s in db.query(Server).order_by(Server.hostname).all()]


# ── 그룹 / 태그 (중앙 UI에서 지정 — import 는 읽기 전용이라 여기서 관리) ──
class GroupIn(BaseModel):
    name: str


@router.get("/groups")
def list_groups(db: Session = Depends(get_db)) -> list[dict]:
    counts: dict[int, int] = {}
    for s in db.query(Server).all():
        if s.group_id:
            counts[s.group_id] = counts.get(s.group_id, 0) + 1
    return [
        {"id": g.id, "name": g.name, "count": counts.get(g.id, 0)}
        for g in db.query(ServerGroup).order_by(ServerGroup.name).all()
    ]


@router.post("/groups")
def create_group(body: GroupIn, db: Session = Depends(get_db)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="이름이 비어 있음")
    g = db.query(ServerGroup).filter(ServerGroup.name == name).first()
    if g is None:
        g = ServerGroup(name=name)
        db.add(g)
        db.commit()
    return {"id": g.id, "name": g.name}


class MetaIn(BaseModel):
    group_id: int | None = None   # null = 그룹 해제
    tags: list[str] | None = None  # None = 태그 변경 안 함


@router.post("/servers/{server_id}/meta")
def set_server_meta(server_id: int, body: MetaIn, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if s is None:
        raise HTTPException(status_code=404, detail="서버를 찾을 수 없음")
    fields = body.model_fields_set
    if "group_id" in fields:  # 준 경우만 변경(null=해제, 미포함=그대로)
        if body.group_id is not None and db.get(ServerGroup, body.group_id) is None:
            raise HTTPException(status_code=400, detail="그룹이 존재하지 않음")
        s.group_id = body.group_id
    if body.tags is not None:
        s.tags = ",".join(t.strip() for t in body.tags if t.strip()) or None
    db.commit()
    groups = {g.id: g.name for g in db.query(ServerGroup).all()}
    return _dump(s, groups)


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

    record(db, "server.import", target_type="servers", detail=f"신규 {created}/총 {len(payload.servers)}")
    db.commit()
    return {"imported_new": created, "total": len(payload.servers)}
