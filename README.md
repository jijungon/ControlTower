# Control Tower

[![CI](https://github.com/jijungon/ControlTower/actions/workflows/ci.yml/badge.svg)](https://github.com/jijungon/ControlTower/actions/workflows/ci.yml)

여러 서버·빌드에 흩어진 **접속키·버전·설정(conf)·업데이트·배포 현황**을 한 곳에서
**수집 → 비교 → 배포**하는 사내 관리 도구. (가칭 Control Tower)

> 전체 기획: [docs/ControlTower-PLAN.md](docs/ControlTower-PLAN.md) · 개발 방법: [docs/DEV.md](docs/DEV.md)

---

## 왜 만드나 (Why)

- 서버가 많고 **15개 게이트웨이(gw) 뒤에 흩어져** 있어, "우리 서버가 몇 대이고 무슨 버전·설정으로 도는지"를 한눈에 보는 곳이 없다.
- 설정이 서버마다 조금씩 어긋나고(드리프트), 누가 언제 바꿨는지 기록이 없다.
- 인증서 만료·밀린 보안 패치·제각각인 배포 방식이 흩어져 방치된다.

→ **중앙 = 기준(정답), 서버 = 실제.** 둘의 차이를 한눈에 보여주고, 기록을 남기며, 안전하게 맞춘다. 이게 이 도구의 뿌리다.

## 무엇을 (What) — 관리 대상 7

| 대상 | 내용 |
|---|---|
| 서버·접속키 인벤토리 | `~/.ssh/config` 기준 서버·gw 목록 + "이 서버는 무슨 키로 들어가나" |
| 빌드 버전 | repo·center(GitLab)의 빌드 node·java·docker 버전 + EOL 매칭 |
| 빌드 설치 항목 | 빌드 시 설치하는 것(Dockerfile `RUN apt/npm`, CI) |
| conf 관리 | 설정 기준본 ↔ 서버 실제본, diff·그룹 배포·롤백 |
| update 관리 | 서버별 밀린 OS 패치(보안 구분) |
| 드리프트 | "기준과 다름"을 전 기능에 관통시키는 배지 |
| CI/CD 배포 현황 | 서비스별 배포 경로·환경 매트릭스·직배포·executor (Phase 5) |

**범위 밖(별도로 뺌):** 파일 공유 + MD 뷰어 → `../MoveFILE/` 별도 프로젝트 · 런타임 설정저장소 중앙화(Valkey/OpenBao/Kong) → 추후 트랙 · PEM(TLS 인증서)·서버 내부 설치 패키지 → 나중.

## 어디서·구조 (Where)

```
                       ssh                nested ssh
  ┌──────────────┐   (local 키)  ┌─────────┐ (gw 보유 키) ┌──────────┐
  │ local PC(러너) │ ───────────▶ │ GW(점프) │ ──────────▶ │ 대상 서버  │
  └──────┬───────┘              └─────────┘             └──────────┘
         │ HTTPS (결과↑ · 기준본↓)
  ┌──────▼───────┐
  │ 사내 VM(중앙)  │  웹·API·DB (Docker) · 키 0 · public IP 불필요 · 사내망 전용
  └──────────────┘
```

- **중앙(사내 VM)**: 웹 UI + API + DB. Docker 컨테이너. **SSH 키를 저장하지 않음**.
- **러너(local)**: 키를 가진 로컬에서 실행. gw를 nested ssh로 통과해 수집·배포, 결과만 중앙에 업로드.
- **코드**: GitHub [`jijungon/ControlTower`](https://github.com/jijungon/ControlTower). 주 개발은 로컬(SQLite).

> **단일 머신은 지금(test·개발) 단계뿐** — 현재는 **로컬 1대가 dev·stg·prod를 겸한다**(`docker compose up -d` = 로컬 상시 운영, `make dev` = 코딩용). 다만 **실제 운영 목표는 중앙(사내 VM) + 러너 분리**이고, 거기서 "중앙 무키"가 진짜 보안이 된다. 그래서 중앙 무키·중앙/러너 split을 **처음부터 지켜** test와 real 구조를 일치시킨다 — 지금 구조 그대로 VM에 이관하면 끝.

## 어떻게 (How)

- **agentless** — 대상 서버·gw에 설치물 없음. 이미 있는 SSH만 사용.
- **동기화** — Pull(수집): 주기적으로 버전·conf 수집 → 기준본과 diff → 배지 / Push(적용): dry-run diff → 승인 → 서버 백업 → 교체 → 검증 → reload, 실패 시 자동 롤백.
- **GitOps** — 설정 기준본은 Git에. 이력·롤백·감사 로그가 공짜.
- **스택** — 중앙 FastAPI + React + SQLite(→PostgreSQL) / 러너 Python(asyncssh). 설정은 `.env` 주입(pydantic-settings·dotenv).
- **얇은 코어** — Redis/Consul/Kong 등 무거운 인프라는 내부에 안 들임(라이선스·SPOF 부담 회피). 대신 나중에 "관리 대상"으로 품는다.
- **개발/테스트** — 로컬 우선(SQLite, `make dev`/`make test`, Docker 불필요). 기능 단위 worktree + PR + CI(pytest 게이트).

## 언제 (When) — 로드맵

| Phase | 내용 | 상태 |
|---|---|---|
| 0. 기반 | 서버 인벤토리·`~/.ssh/config` 임포트·연결 테스트 | ← **다음** |
| 1. 수집(read-only) | 접속키·빌드 버전·conf 수집 + 통합 대시보드 = **MVP** | |
| 2. 배포·동기화 | Git 기준본·드리프트·push 파이프라인·감사 로그 | |
| ~~3. 파일·MD~~ | 별도 프로젝트로 분리(`../MoveFILE/`) | 분리됨 |
| 4. 알림·운영 | 만료/드리프트 알림·업데이트 적용·EOL | |
| 5. CI/CD 현황 | 두 GitLab 파이프라인 파싱·배포 현황 대시보드 | |

**현재 상태:** 스캐폴드 완료 — docker-compose(db·api·web), FastAPI 스켈레톤(+Phase 0 엔드포인트 스텁), 데이터 모델, pytest(6개 통과), GitHub 연결 + CI(pytest). 다음은 Phase 0 구현.

## 빠른 시작 (로컬)

```bash
make setup     # venv + 의존성 + .env (최초 1회)
make dev       # 중앙 API 로컬 실행 (SQLite, hot-reload) → http://127.0.0.1:8000/health
make test      # 전체 테스트
```

전체 스택을 컨테이너로: `docker compose up -d --build` — 로컬에서 이게 곧 **상시 운영(=prod)**이다. `make dev` 는 코딩 중 hot-reload용. 자세한 개발 흐름은 [docs/DEV.md](docs/DEV.md).

## 저장소 구조

```
ControlTower/
├── docker-compose.yml · .env.example · Makefile
├── central/
│   ├── api/          FastAPI 백엔드 (Dockerfile, app/, tests/)
│   └── web/          React 프론트 (placeholder → 추후)
├── db/               schema.sql (데이터 모델 정본)
├── runner/           러너 CLI (로컬 네이티브, tests/)
└── docs/             PLAN · DEV · 빌드환경 체크리스트 · CICD 현황 · 설정저장소(추후 트랙)
```

## 문서

- [docs/ControlTower-PLAN.md](docs/ControlTower-PLAN.md) — 전체 기획(기능·아키텍처·로드맵·열린 질문)
- [docs/DEV.md](docs/DEV.md) — 로컬 개발 · worktree · 테스트 · PR
- [docs/supercycl-CICD-현황.md](docs/supercycl-CICD-현황.md) — Phase 5 근거 조사
- [docs/ControlTower-빌드환경-체크리스트.md](docs/ControlTower-빌드환경-체크리스트.md) — 열린 질문 5 확인용
- [docs/관련과제-설정정책중앙화.md](docs/관련과제-설정정책중앙화.md) — 추후 트랙(런타임 설정저장소)
