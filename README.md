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
- **개발/테스트** — 로컬 우선(SQLite, `make dev`/`make test`, Docker 불필요). 기능 단위 worktree + PR. CI는 **PR마다 빠른 검사(pytest·vitest·gitleaks), merge queue에서 무거운 검사(e2e·image·deps-audit)** — FileSharer 방식.

## IdP-옵셔널 — 나중에 인증 플랫폼에 꽂는 준비

ControlTower는 **혼자서도 그대로 돌고**, 나중에 사내 IdP/Secrets 플랫폼(Authentik + OpenBao SSH CA)이
서면 **환경변수 스위치 3개**만 켜서 붙는다. 코드 수정 없음. (중앙이 SSH 키를 park 하지 않는 원칙의 완성형)

| 어댑터 | 스위치 | 기본(지금) | 플랫폼 모드 |
|---|---|---|---|
| 접속(러너) | `CT_SSH_MODE` | `key` — `~/.ssh/config` 상주 키 | `cert` — OpenBao 단명 SSH 인증서 |
| 로그인(웹) | `CT_AUTH_MODE` | `none` — 로그인 없음 | `oidc` — Authentik OIDC (`GET /api/me`) |
| 비밀(중앙) | `CT_SECRET_MODE` | `env` — `.env`/환경변수 | `vault` — OpenBao KV |

- 각 모드는 **미설정·실패 시 기본으로 폴백**한다(안전). 기본값만 쓰면 예전과 100% 동일하게 동작.
- 플랫폼 자체(Authentik/OpenBao)는 **별도 프로젝트** — 설계·계획은 로컬 전용 `~/Downloads/parameta-idp-secrets/`.

### 운영에서 OpenBao에 붙일 때 (TLS·mTLS)

운영 OpenBao는 HTTPS(사내 CA 발급)에 LB가 mTLS를 요구할 수 있다. 주소가 `https://` 일 때만 적용되며,
`http://`(PoC·개발)에는 **아무 영향이 없다.**

| | 러너(`CT_SSH_MODE=cert`) | 중앙(`CT_SECRET_MODE=vault`) |
|---|---|---|
| 사내 CA 번들(PEM) | `CT_BAO_CACERT` | `CT_VAULT_CACERT` |
| 클라이언트 인증서 | `CT_BAO_CLIENT_CERT` | `CT_VAULT_CLIENT_CERT` |
| 클라이언트 개인키 | `CT_BAO_CLIENT_KEY` | `CT_VAULT_CLIENT_KEY` |
| **실패 시 중단(운영 필수)** | `CT_SSH_CERT_REQUIRED=1` | `CT_SECRET_REQUIRED=1` |

> ⚠️ **`*_REQUIRED`를 운영에서 반드시 켠다.** 폴백은 개발 편의를 위한 것이라, 켜지 않으면
> TLS·토큰 문제로 OpenBao 연동이 깨져도 러너는 **상주 키로 계속 접속**하고 중앙은
> **공개된 기본값(`dev-secret-change-me`)으로 기동**한다 — 둘 다 조용히 일어난다.
> 켜지 않아도 실패는 이제 `stderr` 경고로 남는다.

> ⚠️ 사내망에 **TLS 검사 프록시**가 있으면 중간에서 인증서를 갈아끼우기 때문에 mTLS가 깨진다.
> OpenBao 엔드포인트는 프록시 **검사 예외(bypass)** 목록에 넣어야 한다.

## 언제 (When) — 로드맵

| Phase | 내용 | 상태 |
|---|---|---|
| 0. 기반 | 서버 인벤토리·`~/.ssh/config` 임포트·연결 테스트 | ← **다음** |
| 1. 수집(read-only) | 접속키·빌드 버전·conf 수집 + 통합 대시보드 = **MVP** | |
| 2. 배포·동기화 | Git 기준본·드리프트·push 파이프라인·감사 로그 | |
| ~~3. 파일·MD~~ | 별도 프로젝트로 분리(`../MoveFILE/`) | 분리됨 |
| 4. 알림·운영 | 만료/드리프트 알림·업데이트 적용·EOL | |
| 5. CI/CD 현황 | 두 GitLab 파이프라인 파싱·배포 현황 대시보드 | |

**현재 상태:** 7개 탭 전부 실데이터로 연결됨 — 서버·접속키(그룹·태그·필터), conf(드리프트 + 계획→승인→적용→롤백), 업데이트(apt), 버전(빌드서버 툴체인 + GitLab 선언본), CI/CD 현황, 작업이력(감사), 대시보드. 러너 수집기(import/test/conf/updates/versions/versions-repo/cicd) + `all`(주기 수집) + `apply`(안전 배포). **접속·로그인·비밀 3개 어댑터로 IdP-옵셔널 준비 완료**(위 § 참조). CI 6잡(backend·frontend·gitleaks·deps-audit·image·e2e) — PR은 빠르게 / merge queue는 꼼꼼. GitLab 실연결만 인스턴스 준비 대기(코드 완비).

## 빠른 시작 (로컬)

```bash
make setup     # venv + 의존성 + .env (최초 1회)
make dev       # 중앙 API 로컬 실행 (SQLite, hot-reload) → http://127.0.0.1:8000/health (version·build 포함)
make test      # 전체 테스트
```

전체 스택을 컨테이너로: `docker compose up -d --build` → 웹 http://127.0.0.1:8090 · API http://127.0.0.1:8000. 로컬에서 이게 곧 **상시 운영(=prod)**이다. `make dev` 는 코딩 중 hot-reload용. 개발 흐름 [docs/DEV.md](docs/DEV.md) · **사내 VM 배포 [docs/DEPLOY.md](docs/DEPLOY.md)**.

주기 수집(모든 수집기 1회): `make collect` — cron 에 등록하면 데이터가 계속 최신으로 유지된다.
상주 실행: `python -m runner.cli all --loop --interval 300`.

## GitLab 연동 켜기

CI/CD 파이프라인 상태와 repo 선언본 버전(node/nest/java)은 GitLab 에서 읽는다. GitLab 이 준비되면:

1. **러너 `.env`** 에 토큰 설정 (러너 로컬에만 — 중앙엔 저장 안 함):
   ```
   CT_GITLAB_URL=https://gitlab.example.com
   CT_GITLAB_TOKEN=glpat-xxxxxxxx    # read_api 스코프면 충분
   ```
2. **웹에서 대상 등록**:
   - CI/CD 탭 → *서비스 추가* (서비스 이름 + `group/repo`)
   - 버전·빌드 탭 → *GitLab 선언본 대상 추가*
3. **러너 실행**: `python -m runner.cli cicd` (파이프라인) · `versions-repo` (선언본).
   `make collect` / cron 도 GitLab 설정 시 이 둘을 포함한다.

> GitLab 이 아직이면 이 두 기능만 비어 있고, 나머지(서버·conf·업데이트·툴체인·작업이력)는 그대로 동작한다. 토큰은 **러너 로컬에만** 두며 중앙 DB엔 결과 상태만 저장된다.

### 서비스 비교표 · config (빌드·배포 탭 / config 탭)

- **빌드·배포 탭** — CI 가 **어떻게 빌드·배포하나**(CI 파일 기준). 그룹(프로젝트 묶음) → 서비스 → 타입(web·was)으로 묶어 **환경별 배포(파일 복사 · repo / 파일 복사 · center / 이미지 / 빌드만) · executor**를 나란히 비교. 표 위 "표 읽는 법"에 각 칸의 뜻.
- **config 탭** — 이미지가 **무엇으로, 어떻게 실행되나**(config repo + 서버 compose 기준). 폴더(서비스/타입)마다 **런타임·베이스 이미지(같은 종류 중 최신이 아니면 빨간 칸, 런타임 필터) · 실행 명령 위치(Dockerfile CMD / start.sh) · start.sh 상태(구형/잔재/완료) · start.sh 형태**(서버 compose 기준: shell = start.sh 마운트 / compose = `command:` 직접 / Dockerfile = 이미지 CMD) 표시.

1. `cp runner/shape-targets.example.yml shape-targets.yml` 후 읽을 파일을 적는다 (커밋 안 됨).
   - GitLab: `{gitlab: repo|center, project, path}` — center 는 별도 인스턴스라 `CT_GITLAB_CENTER_URL/TOKEN`
   - 로컬 사본: `{file: 경로}` · 서버의 실제 파일(compose 등): `{ssh: 호스트별칭, path}`
   - `config:` 에 config repo 를 적으면 폴더를 자동으로 훑고, 서비스는 `config_dir:` 로 연결
2. `python -m runner.cli shape` (`make collect` 도 대상 파일이 있으면 포함)
3. 서버 compose 를 실서버에서 읽기(선택): center CI 의 `DEPLOY_<환경>[_<타입>]_SERVERS` 와 `APP_DIR` 로 서버·폴더를 찾아
   - `python -m runner.cli shape --ssh-plan` — 어느 서버의 어떤 파일을 읽을지 **목록만** (접속 안 함)
   - `python -m runner.cli shape --ssh` — 그 목록대로 SSH 로 읽음(읽기만). 서버가 `~/.ssh/config` 에 직접 있거나,
     대상 파일의 `gateways:`(환경 → gw 별칭)를 거쳐 들어감(PC → gw → 서버, 안쪽은 gw 의 키·설정)
     - gw 의 `~/.ssh/config` 에 이름으로 등록된 서버는 그 이름으로 접속(gw 가 맞춰 둔 계정·키·지문 그대로)
     - 안쪽 서버가 gw 의 root 계정에만 등록돼 있으면 `gateway_sudo: [gw 별칭]` — `sudo -n` 으로 root 설정을 씀(읽기만)
     - CI 에 배포 단계가 없는 서비스는 `compose: {prod: {ssh: <gw 의 이름>, via: <gw 별칭>, path: …}}` 로 직접 적기
   - 이미지 하나를 역할별로 나눠 띄우는 서비스: `type`(표에 보일 이름) · `tag_type`(태그·폴더 타입) · `deploy_role`(`DEPLOY_<환경>_<역할>_SERVERS`)
     — config 탭은 역할마다 한 줄(옆에 실제 폴더)
   - config 탭 (서버) 칸 옆에 출처 표시: 서버 · 자동 · gw · 사본 · 옛 사본 (좁은 화면에선 마우스로)

> 읽기 전용. 읽은 파일 원문은 중앙에 올리지 않고 결과 칸만 올린다. CI 변수는 **값 없이** 개수 + 해시만 보낸다(화면엔 안 보임). executor 는 GitLab 이 알려주지 않으므로 대상 파일의 `runners:` 표(태그→shell/docker)로 정하고, 표에 없는 태그는 `(추정)`.

### 탭별 출처 — 고칠 때 어디를 보면 되나

기준: **방식(어떻게)은 빌드·배포, 버전(무엇으로)은 config, 서버에 깔린 것은 서버 탭.** 화면의 표마다 같은 "출처" 줄이 붙어 있다.

| 탭 · 표 | 무엇을 | 어디서 읽나 | 수집(러너) | API · 화면 코드 |
|---|---|---|---|---|
| 대시보드 | 아래 수집 결과 요약 | (각 탭 데이터) | — | `Dashboard.tsx` |
| 서버 · 서버 목록 | 서버·접속 키·접속 확인 | 내 PC `~/.ssh/config` · SSH 접속 | `import` · `test` · `probe` | `/api/servers` · `Servers.tsx` |
| 서버 · 깔린 도구 칸 | 서버마다 node/java/docker 버전 | 서버마다 SSH 로 `--version` | `versions` | `/api/versions` · `Servers.tsx` |
| 서버 · 서버 설정 파일 (/etc) | 서버마다 같아야 하는 파일 비교·적용 | 서버마다 SSH 로 등록한 파일 | `conf` · `apply` | `/api/conf` · `Conf.tsx` |
| 빌드·배포 · 서비스 비교 | 환경별 배포 방식 · executor | repo·center `.gitlab-ci.yml` (+ 서버 compose 로 확인) | `shape` (대상 `shape-targets.yml`) | `/api/cicd/shape` · `CicdCompare.tsx` |
| config · config 폴더 | 코드에 적힌 버전 · 런타임/베이스 이미지 · 실행 명령 위치 · start.sh 상태·형태 | center config repo(Dockerfile·start.sh) · repo 코드(`.nvmrc`·`package.json`·`pom.xml`) · 서버 compose | `shape` (대상 `shape-targets.yml`) | `/api/cicd/config` · `ConfigRepo.tsx` |
| OS 패치·작업이력 · OS 패치 | 서버마다 안 깔린 패치 | 서버마다 SSH 로 apt(→yum/dnf) | `updates` | `/api/updates` · `Updates.tsx` |
| OS 패치·작업이력 · 작업이력 | ControlTower 가 한 모든 일 | 중앙 API 가 기록 | — | `/api/audit` · `Jobs.tsx` |

- 수집은 `python -m runner.cli <명령>`, 한 번에 다 돌리려면 `all` (`make collect`).
- 판독 규칙은 `runner/cishape.py`(CI·Dockerfile·compose·코드 버전), 버전 비교(빨간 칸)는 `central/web/src/vercmp.tsx`.
- 표마다 ↻ 는 **화면 새로고침**(중앙에 저장된 값을 다시 읽음)이다. 서버·GitLab 을 다시 읽는 건 러너 몫.
- 쓰지 않게 된 것: 파이프라인 상태(`runner cicd`, `/api/cicd`·`/api/cicd/targets`)와 GitLab 선언본 대상(`runner versions-repo`, `/api/versions/repo-*`)은 화면에서 뺐다. 코드에 적힌 버전은 이제 `shape` 가 config 탭으로 모은다.

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
