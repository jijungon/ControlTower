"""버전 관리 (Phase 3) — 툴체인/선언본 버전.

두 소스를 하나의 매트릭스로:
  - server: 빌드 서버 툴체인(`node --version` 등) → tool_snapshots (러너 ssh)
  - repo:   GitLab repo 선언본(package.json engines·@nestjs/core, pom.xml) → repo_versions (러너 GitLab)
GET /api/versions 는 kind(server|repo)·name·tools 로 합쳐 돌려준다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import record
from ..auth import require_runner
from ..db import get_db
from ..models import RepoVersion, Server, ToolSnapshot, VersionTarget

router = APIRouter(prefix="/api/versions", tags=["versions"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 빌드 서버 툴체인 스냅샷 (러너 ssh) ───────────────────────────────
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


# ── repo 선언본: 대상(repo↔GitLab 프로젝트) ─────────────────────────
class RepoTargetIn(BaseModel):
    repo: str
    project: str


@router.get("/repo-targets")
def list_repo_targets(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(VersionTarget).order_by(VersionTarget.repo).all()
    return [{"repo": t.repo, "project": t.project} for t in rows]


@router.post("/repo-targets")  # 대상 등록은 UI 액션 — open. 스냅샷 업로드(/repo-snapshots)만 러너 토큰.
def add_repo_target(body: RepoTargetIn, db: Session = Depends(get_db)) -> dict:
    row = db.query(VersionTarget).filter(VersionTarget.repo == body.repo).first()
    if row is None:
        row = VersionTarget(repo=body.repo)
        db.add(row)
    row.project = body.project
    db.commit()
    return {"ok": True, "repo": body.repo}


# ── repo 선언본: 스냅샷 업로드 (러너 GitLab) ─────────────────────────
class RepoSnapshotIn(BaseModel):
    repo: str
    tool: str
    version: str | None = None


class RepoSnapshotBatch(BaseModel):
    snapshots: list[RepoSnapshotIn]


@router.post("/repo-snapshots", dependencies=[Depends(require_runner)])
def upload_repo_snapshots(batch: RepoSnapshotBatch, db: Session = Depends(get_db)) -> dict:
    now = _now()
    for s in batch.snapshots:
        row = (
            db.query(RepoVersion)
            .filter(RepoVersion.repo == s.repo, RepoVersion.tool == s.tool)
            .first()
        )
        if row is None:
            row = RepoVersion(repo=s.repo, tool=s.tool)
            db.add(row)
        row.version = s.version
        row.collected_at = now
    record(db, "versions.repo_collect", target_type="versions", detail=f"{len(batch.snapshots)}건")
    db.commit()
    return {"accepted": len(batch.snapshots)}


# ── 통합 매트릭스 (server + repo) ────────────────────────────────────
def _merge(name: str, kind: str, tool: str, version: str | None, collected_at: str | None, acc: dict) -> None:
    entry = acc.setdefault((kind, name), {"kind": kind, "name": name, "tools": {}, "collected_at": collected_at})
    if version:
        entry["tools"][tool] = version
    if collected_at and (entry["collected_at"] is None or collected_at > entry["collected_at"]):
        entry["collected_at"] = collected_at


@router.get("")
def versions_matrix(db: Session = Depends(get_db)) -> list[dict]:
    servers = {s.id: s for s in db.query(Server).all()}
    acc: dict = {}
    for snap in db.query(ToolSnapshot).all():
        name = servers[snap.server_id].hostname if snap.server_id in servers else str(snap.server_id)
        _merge(name, "server", snap.tool, snap.version, snap.collected_at, acc)
    for rv in db.query(RepoVersion).all():
        _merge(rv.repo, "repo", rv.tool, rv.version, rv.collected_at, acc)
    # 서버 먼저, 그다음 repo, 각각 이름순
    return sorted(acc.values(), key=lambda r: (0 if r["kind"] == "server" else 1, r["name"]))
