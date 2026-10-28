"""SQLAlchemy 모델 — db/schema.sql 의 Phase 0 테이블 미러(핵심만).

중앙은 SSH 키를 저장하지 않는다. credential_refs 는 별칭·지문 등 메타만.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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
    tags: Mapped[str | None] = mapped_column(String, nullable=True)           # 콤마 구분(중앙 UI에서 지정)
    needs_2fa: Mapped[int | None] = mapped_column(Integer, nullable=True)     # 접속 점검(probe): 1=추가인증 필요, 0=키단독, NULL=미확인
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


class ServiceShape(Base):
    """서비스 비교표 한 행(러너 판독 결과). service 당 하나, 수집 때마다 덮어씀.

    env 는 값 없이 해시만 받는다 — 해시가 바뀐 시각(env_changed_at)으로 '언제 바뀌었나'를 보여준다.
    """
    __tablename__ = "service_shapes"
    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String, unique=True)
    group_name: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[str] = mapped_column(Text, default="{}")                 # JSON: 런타임·배포·executor·start.sh…
    env_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    env_changed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ConfigItem(Base):
    """center config repo 의 폴더 하나(<서비스>/<타입>) 판독 결과. 수집 때마다 덮어씀(파일 원문은 저장 안 함)."""
    __tablename__ = "config_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)                # 예: shop/web
    data: Mapped[str] = mapped_column(Text, default="{}")                 # JSON: 베이스 이미지·실행 명령 위치·start.sh·start.sh 형태
    collected_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ── 다시 수집(화면 버튼 → 수집기) ───────────────────────────────────────

class CollectRequest(Base):
    """화면 [다시 수집] 버튼이 남기는 요청. 중앙은 키·토큰이 없어 직접 수집하지 않고, 수집기(agent)가 가져가 처리한다."""
    __tablename__ = "collect_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)                             # shape(빌드·배포·config)
    status: Mapped[str] = mapped_column(String, default="pending")        # pending | running | done | failed
    requested_at: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    collector: Mapped[str | None] = mapped_column(String, nullable=True)  # 가져간 수집기 이름
    message: Mapped[str | None] = mapped_column(Text, nullable=True)      # 결과 한 줄(요약·실패 이유)
    trigger: Mapped[str | None] = mapped_column(String, nullable=True, default="user")  # user(버튼) | auto(매일 정해 둔 시각)


class Collector(Base):
    """수집기(agent)가 마지막으로 요청을 확인한 시각 — 화면에서 '수집기가 꺼져 있어요' 판단용."""
    __tablename__ = "collectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    mode: Mapped[str | None] = mapped_column(String, nullable=True)       # gitlab | gitlab+ssh (무엇을 읽나)
    schedule: Mapped[str | None] = mapped_column(String, nullable=True)   # 자동 수집 시각(예: '09:00 Asia/Seoul'), 없으면 버튼만
    last_seen_at: Mapped[str | None] = mapped_column(String, nullable=True)


class HostStatus(Base):
    """서버가 스스로 적는 상태 파일(예: IdP 서버 status.json)을 수집기가 읽어 올린 마지막 모습 — source 마다 한 줄.

    못 읽었으면(read_ok=False) 이유만 바꾸고, 마지막으로 읽은 내용(written_at · problems …)은 남겨 둔다(화면에 '마지막 기록').
    정상/경보/낡음/모름 판정은 조회할 때 지금 시각으로 한다 — 저장된 값이 낡아 가는 것 자체를 경보로 보려고.
    """
    __tablename__ = "host_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, unique=True)                  # idp(IdP 서버) …
    reader: Mapped[str | None] = mapped_column(String, nullable=True)         # 올린 수집기 이름
    received_at: Mapped[str | None] = mapped_column(String, nullable=True)    # 중앙이 마지막으로 받은 시각
    read_ok: Mapped[bool] = mapped_column(Boolean, default=False)             # 수집기가 파일을 읽었나
    read_error: Mapped[str | None] = mapped_column(Text, nullable=True)       # 못 읽은 이유(파일 없음 · JSON 깨짐 …)
    written_at: Mapped[str | None] = mapped_column(String, nullable=True)     # 적는 쪽이 파일에 적은 시각
    host: Mapped[str | None] = mapped_column(String, nullable=True)           # 파일의 host(서버 이름은 런타임에만)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    problems: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON 목록 — 확인된 문제
    unread: Mapped[str | None] = mapped_column(Text, nullable=True)           # JSON 목록 — 보려 했는데 못 본 것
    signals: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON — 신호별 원본(화면 펼침용)


class IdpPeople(Base):
    """사람 이름표(Authentik 의 server-admin · developer 사람 목록)를 수집기가 읽어 올린 마지막 모습 — source 마다 한 줄.

    IdP 서버가 5분마다 통째로 다시 쓰는 파일이라 쌓지 않고 올 때마다 통째로 바꾼다. 못 읽었으면 목록도 비운다
    (지난 이름을 지금 것처럼 남기지 않음). 정상/모름/멈춤 판정은 조회할 때 지금 시각으로 — routers/idp_people.py.
    """
    __tablename__ = "idp_people"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, unique=True)                  # idp
    reader: Mapped[str | None] = mapped_column(String, nullable=True)         # 올린 수집기 이름
    received_at: Mapped[str | None] = mapped_column(String, nullable=True)    # 중앙이 마지막으로 받은 시각
    read_ok: Mapped[bool] = mapped_column(Boolean, default=False)             # 수집기가 파일을 읽었나
    read_error: Mapped[str | None] = mapped_column(Text, nullable=True)       # 못 읽은 이유(파일 없음 · 머리 줄 깨짐 …)
    written_at: Mapped[str | None] = mapped_column(String, nullable=True)     # IdP 가 파일에 적은 시각
    host: Mapped[str | None] = mapped_column(String, nullable=True)           # 적은 서버(이름은 런타임에만)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 다시 쓰는 주기(보통 300)
    origin: Mapped[str | None] = mapped_column(String, nullable=True)         # 파일 머리의 source(authentik)
    list_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)      # IdP 가 Authentik 을 읽었나(파일 머리의 read_ok)
    list_reason: Mapped[str | None] = mapped_column(Text, nullable=True)      # 못 읽은 까닭(파일 머리의 why)
    groups: Mapped[str | None] = mapped_column(Text, nullable=True)           # JSON — 그룹별 사람 수(비활성 포함), 모르면 null
    header_people: Mapped[int | None] = mapped_column(Integer, nullable=True)  # IdP 가 적었다는 사람 수
    person_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 수집기가 받은 사람 줄(깨진 것 포함)
    bad_lines: Mapped[int] = mapped_column(Integer, default=0)                # 수집기가 깨져서 뺀 줄 수
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)           # 너무 많아 잘랐나
    people: Mapped[str | None] = mapped_column(Text, nullable=True)           # JSON 목록 — 이메일 · 아이디 · 이름 · 그룹 · 활성

class AccessLogSnapshot(Base):
    """금고(IdP) 접속 기록 요약 파일을 수집기가 읽어 올린 마지막 모습 — source 마다 한 줄, 올 때마다 통째로 바꾼다.

    source 'idp' = access.jsonl(인증서 발급 기록), 'idp-gw' = gw-logins.jsonl(gw 에 실제로 들어간 기록 — events 가
    gw 접속 한 번씩, reports · gws · bad_gws 는 이 줄만 씀). 두 파일은 머리 모양이 같아 한 표에 둔다.
    파일 자체가 '최근 14일치' 라 쌓지 않는다(보존은 IdP 쪽 원본 몫). 정상/못 봄/멈춤 판정은 조회할 때 지금 시각으로.
    파일이 없으면(IdP 반영 전 포함) '못 봄' — 빈 표로 보이지 않게.
    """
    __tablename__ = "access_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, unique=True)                  # idp(금고 기록)
    reader: Mapped[str | None] = mapped_column(String, nullable=True)         # 올린 수집기 이름
    received_at: Mapped[str | None] = mapped_column(String, nullable=True)    # 중앙이 마지막으로 받은 시각
    read_ok: Mapped[bool] = mapped_column(Boolean, default=False)             # 수집기가 파일을 읽었나
    read_error: Mapped[str | None] = mapped_column(Text, nullable=True)       # 못 읽은 이유(파일 없음 · 머리 줄 깨짐 …)
    written_at: Mapped[str | None] = mapped_column(String, nullable=True)     # IdP 가 파일에 적은 시각
    host: Mapped[str | None] = mapped_column(String, nullable=True)           # 적은 서버(이름은 런타임에만)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 다시 쓰는 주기(보통 60)
    window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 며칠치인가(보통 14)
    audit_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)     # IdP 가 금고 기록을 읽었나(파일 머리의 read_ok)
    audit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)     # 못 읽은 까닭(파일 머리의 why)
    files_read: Mapped[int | None] = mapped_column(Integer, nullable=True)    # IdP 가 읽은 금고 기록 파일 수 — 0 이면 '못 봄'
    lines_read: Mapped[int | None] = mapped_column(Integer, nullable=True)    # IdP 가 읽은 금고 기록 줄 수(있으면) — 0 이면 '못 봄'
    source_bad_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)  # IdP 가 금고 기록에서 못 읽은 줄
    header_events: Mapped[int | None] = mapped_column(Integer, nullable=True)  # IdP 가 적었다는 건수
    event_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 수집기가 받은 이벤트 줄(깨진 것 포함)
    bad_lines: Mapped[int] = mapped_column(Integer, default=0)                # 수집기가 깨져서 뺀 줄 수
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)           # 최근 몇천 건까지만 넘겼나
    events: Mapped[str | None] = mapped_column(Text, nullable=True)           # JSON 목록 — 인증서 발급 · 거부(idp-gw: gw 접속)
    reports: Mapped[int | None] = mapped_column(Integer, nullable=True)       # (idp-gw) IdP 가 읽은 gw 보고 수
    gws: Mapped[str | None] = mapped_column(Text, nullable=True)              # (idp-gw) JSON 목록 — gw 마다 마지막 보고. NULL = 모름
    bad_gws: Mapped[int | None] = mapped_column(Integer, nullable=True)       # (idp-gw) 깨져서 뺀 gw 보고 칸


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
