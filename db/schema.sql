-- Control Tower — Phase 0 데이터 모델 (중앙 DB)
--
-- 원칙:
--   * 중앙 VM은 SSH 키를 저장하지 않는다. credential_refs 는 '별칭(alias)'만 보관하고
--     실제 키는 러너(local) 키스토어가 alias 로 resolve 한다.
--   * gw(게이트웨이)도 servers 에 role='gateway' 로 등록한다(자격증명·감사를 동일 관리).
--   * 접속 경로는 servers.access_method + gateway_id 로 표현한다(nested ssh 체인 가능).
--
-- 대상 DB: SQLite 로 시작 → PostgreSQL 이관. 아래는 이식성 위주 DDL.
-- (Postgres 이관 시 INTEGER PRIMARY KEY → SERIAL/IDENTITY, datetime('now') → now() 로 치환)

PRAGMA foreign_keys = ON;

-- 그룹 (환경/역할 단위) --------------------------------------------------------
CREATE TABLE server_groups (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

-- 태그 (다대다) — 대규모에서 필터·그룹 배포에 사용 --------------------------------
CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- 자격증명 '참조'만 보관 (실제 비밀 없음) ---------------------------------------
-- 러너 키스토어가 alias -> 실제 키 경로를 매핑한다. 여기에 키/비번 원문 저장 금지.
CREATE TABLE credential_refs (
    id              INTEGER PRIMARY KEY,
    alias           TEXT NOT NULL UNIQUE,
    username        TEXT NOT NULL,
    auth_type       TEXT NOT NULL DEFAULT 'key',   -- key | password (둘 다 실체는 러너 로컬)
    -- '무엇으로 들어가는지' 메타(키 실체 아님): 파일명·지문만. ~/.ssh/config 임포트로 채움.
    key_file        TEXT,          -- IdentityFile basename (예: gw_prod_ed25519)
    key_fingerprint TEXT,          -- ssh-keygen -lf 의 SHA256 지문
    source          TEXT NOT NULL DEFAULT 'manual',   -- manual | ssh_config
    description     TEXT
);

-- 서버/게이트웨이 인벤토리 -----------------------------------------------------
CREATE TABLE servers (
    id               INTEGER PRIMARY KEY,
    hostname         TEXT NOT NULL,
    ip               TEXT,
    ssh_port         INTEGER NOT NULL DEFAULT 22,
    ssh_user         TEXT NOT NULL,
    os               TEXT DEFAULT 'ubuntu',
    os_version       TEXT,
    role             TEXT NOT NULL DEFAULT 'target',    -- target | gateway
    -- 접속 경로: 직접 or 게이트웨이 경유(nested ssh). gateway_id 는 role='gateway' 서버.
    access_method    TEXT NOT NULL DEFAULT 'direct',    -- direct | via_gateway
    gateway_id       INTEGER REFERENCES servers(id),
    -- 러너가 키를 resolve 할 별칭. 중앙은 실제 키를 저장하지 않음.
    credential_alias TEXT REFERENCES credential_refs(alias),
    group_id         INTEGER REFERENCES server_groups(id),
    status           TEXT NOT NULL DEFAULT 'unknown',   -- unknown | online | offline
    last_checked_at  TEXT,
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE server_tags (
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (server_id, tag_id)
);

-- 러너 등록 (러너는 API 토큰으로 중앙에 인증) -----------------------------------
CREATE TABLE runners (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    api_token_hash TEXT NOT NULL,      -- 토큰 원문 저장 금지(해시만)
    last_seen_at   TEXT,
    status         TEXT NOT NULL DEFAULT 'unknown',
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 연결 테스트 결과 (Phase 0 완료 기준: 전 서버 연결 OK) --------------------------
CREATE TABLE connection_tests (
    id         INTEGER PRIMARY KEY,
    server_id  INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    runner_id  INTEGER REFERENCES runners(id),
    ok         INTEGER NOT NULL,        -- 0/1
    latency_ms INTEGER,
    error      TEXT,
    tested_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 사용자 / RBAC ---------------------------------------------------------------
CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT,
    role         TEXT NOT NULL DEFAULT 'viewer',   -- admin | operator | viewer
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 감사 로그 (append-only) — 처음부터 남긴다 ------------------------------------
CREATE TABLE audit_logs (
    id          INTEGER PRIMARY KEY,
    actor       TEXT NOT NULL,          -- 'user:email' 또는 'runner:name'
    action      TEXT NOT NULL,          -- 예: server.create, conn.test, credential.view
    target_type TEXT,
    target_id   TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_servers_role     ON servers(role);
CREATE INDEX idx_servers_gateway  ON servers(gateway_id);
CREATE INDEX idx_servers_group    ON servers(group_id);
CREATE INDEX idx_conn_tests_server ON connection_tests(server_id);
CREATE INDEX idx_audit_created    ON audit_logs(created_at);
