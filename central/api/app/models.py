"""SQLAlchemy 모델 — db/schema.sql 의 Phase 0 테이블 미러(핵심만).

중앙은 SSH 키를 저장하지 않는다. credential_refs 는 별칭·지문 등 메타만.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ServerGroup(Base):
    __tablename__ = "server_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class CredentialRef(Base):
    __tablename__ = "credential_refs"
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String, unique=True)
    username: Mapped[str] = mapped_column(String)
    auth_type: Mapped[str] = mapped_column(String, default="key")
    key_file: Mapped[str | None] = mapped_column(String, nullable=True)          # IdentityFile basename
    key_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)   # SHA256 지문
    source: Mapped[str] = mapped_column(String, default="manual")                # manual | ssh_config
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Server(Base):
    __tablename__ = "servers"
    id: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String)
    os: Mapped[str | None] = mapped_column(String, default="ubuntu")
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="target")               # target | gateway
    access_method: Mapped[str] = mapped_column(String, default="direct")      # direct | via_gateway
    gateway_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id"), nullable=True)
    credential_alias: Mapped[str | None] = mapped_column(String, nullable=True)
    access_control: Mapped[str | None] = mapped_column(String, nullable=True)  # dbsafe·ncloud 등 (NULL=일반)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("server_groups.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="unknown")            # unknown | online | offline
    last_checked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Runner(Base):
    __tablename__ = "runners"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    api_token_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="unknown")


class ConnectionTest(Base):
    __tablename__ = "connection_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    runner_id: Mapped[int | None] = mapped_column(ForeignKey("runners.id"), nullable=True)
    ok: Mapped[int] = mapped_column(Integer)                # 0/1
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── conf 관리 (Phase 1) ──────────────────────────────────────────────

class ConfTarget(Base):
    """관리 대상 conf 파일 경로 (러너가 이 경로들을 수집)."""
    __tablename__ = "conf_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)   # 예: /etc/nginx/nginx.conf


class ConfBaseline(Base):
    """중앙 기준본(정답). path 당 하나."""
    __tablename__ = "conf_baselines"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ConfSnapshot(Base):
    """서버에서 수집한 실제본. (server_id, path) 당 최신 하나로 upsert."""
    __tablename__ = "conf_snapshots"
    __table_args__ = (UniqueConstraint("server_id", "path", name="uq_conf_snapshot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    path: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)   # 읽기 실패(없음/권한 등)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ConfApplyIntent(Base):
    """conf 적용(배포) 의도. plan→approve→apply 상태머신. 러너는 approved 만 적용한다.

    쓰기(서버 파일 교체)는 러너가 수행하고, 중앙은 의도·승인·결과만 기록한다.
    """
    __tablename__ = "conf_apply_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    path: Mapped[str] = mapped_column(String)
    from_sha: Mapped[str | None] = mapped_column(String, nullable=True)   # 현재 실제본
    to_sha: Mapped[str | None] = mapped_column(String, nullable=True)     # 목표 기준본
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)         # plan 시 미리보기(unified)
    status: Mapped[str] = mapped_column(String, default="pending")        # pending|approved|applied|failed|canceled
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 러너가 남긴 백업(PR-B)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ── 업데이트 관리 (Phase 2) ──────────────────────────────────────────

class UpdateSnapshot(Base):
    """서버별 대기 중인 OS 패치(apt upgradable). server_id 당 최신 하나로 upsert."""
    __tablename__ = "update_snapshots"
    __table_args__ = (UniqueConstraint("server_id", name="uq_update_snapshot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    packages: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{name,from,to,security}]
    error: Mapped[str | None] = mapped_column(String, nullable=True)   # 수집 실패(접속/권한 등)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ── 버전 관리 (Phase 3) ──────────────────────────────────────────────

class ToolSnapshot(Base):
    """빌드 서버 툴체인 버전(node/java/docker 등). (server_id, tool) 당 최신 하나."""
    __tablename__ = "tool_snapshots"
    __table_args__ = (UniqueConstraint("server_id", "tool", name="uq_tool_snapshot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id"))
    tool: Mapped[str] = mapped_column(String)                          # node · java · docker ...
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


class VersionTarget(Base):
    """버전 선언본을 읽을 repo ↔ GitLab 프로젝트 매핑."""
    __tablename__ = "version_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String, unique=True)             # 표시 이름
    project: Mapped[str] = mapped_column(String)                       # GitLab 경로(group/repo) 또는 id


class RepoVersion(Base):
    """GitLab repo 선언본 버전(package.json engines·@nestjs/core, pom.xml 등). (repo, tool) 당 하나."""
    __tablename__ = "repo_versions"
    __table_args__ = (UniqueConstraint("repo", "tool", name="uq_repo_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String)                          # node · nest · java ...
    tool: Mapped[str] = mapped_column(String)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ── CI/CD 현황 (Phase 5) ─────────────────────────────────────────────

class CicdTarget(Base):
    """추적할 서비스 ↔ GitLab 프로젝트 매핑."""
    __tablename__ = "cicd_targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String, unique=True)
    project: Mapped[str] = mapped_column(String)          # GitLab 경로(group/repo) 또는 숫자 id


class PipelineStatus(Base):
    """서비스별 최근 파이프라인 상태(소스 무관 업서트). service 당 하나."""
    __tablename__ = "pipeline_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String, unique=True)
    has_cicd: Mapped[int] = mapped_column(Integer, default=0)             # 0/1
    status: Mapped[str | None] = mapped_column(String, nullable=True)     # success/failed/running...
    ref: Mapped[str | None] = mapped_column(String, nullable=True)        # 브랜치
    sha: Mapped[str | None] = mapped_column(String, nullable=True)
    web_url: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ── 작업이력 / 감사 로그 ─────────────────────────────────────────────

class AuditLog(Base):
    """러너·사용자 액션 기록(수집·테스트·채택 등). 최신순 조회."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String)                            # runner | user:email
    action: Mapped[str] = mapped_column(String)                           # server.import, conn.test, ...
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
