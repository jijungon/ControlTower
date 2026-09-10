# 서버 중앙 관리 서비스 플랜 (가칭: Control Tower) — v0.2 축약본

> 여러 서버·빌드에 흩어진 접속키·버전·설정(conf)·업데이트·배포 현황을 중앙에서 **수집 → 비교 → 배포**하는 사내 관리 도구. (2026-09-09, 스코프 개편 2026-09-10)

## 원칙

1. **중앙 = 기준(desired), 서버 = 실제(actual).** 본질은 둘의 차이(드리프트)를 한눈에 보여주고 맞추는 것
2. **읽기(수집)부터, 쓰기(배포)는 나중에** — Phase 1은 read-only로 안전하게 가치 검증
3. **모든 변경은 기록되고 되돌릴 수 있다** — Git 이력 + 서버측 백업 + 감사 로그

## 기능 (확정)

| 기능 | 핵심 |
|---|---|
| 서버·접속키 인벤토리 | **`~/.ssh/config` 기준** — config에 등록된 서버만 관리(호스트·gw·user·접속 키 매핑). + 로컬 키/`.pem` 파일 인벤토리(`~/.ssh/`의 aws-key, `~/Downloads/*.pem` 등 — 파일명·지문만, 무저장). "이 서버는 뭘로 들어가나 / 이 키 쓰는 서버는?" 양방향 |
| 빌드 버전 관리 | repo·center·config(GitLab)에서 **빌드에 쓰는 버전** 관리 — node·java·docker(builder) + 레포 선언본(node·nest·java). 대상×버전 매트릭스, EOL 매칭 |
| 빌드 설치 항목 | 빌드 시 설치하는 항목(Dockerfile `RUN apt/npm`, CI install 스텝) 관리. ※ **서버 내부 설치 패키지 인벤토리는 나중에** |
| conf 관리 | Git 기반 중앙 기준본(이력·롤백), 서버 실제본 수집·diff, 템플릿 변수로 그룹 일괄 적용. 대상 타입 `file`부터(→나중 kong·consul-kv) |
| update 관리 | 서버별 대기 OS 업데이트 수집(apt), 보안 패치 구분. dry-run→승인→그룹 적용 (v1은 현황만) |
| 드리프트 | 주기 스캔 → `동기화됨/드리프트/미수집` 배지. 자동 덮어쓰기 없음 — diff 후 채택(서버→중앙) 또는 복원(중앙→서버) |
| CI/CD 배포 현황 | **등록된 프로젝트**에 대해 서비스별로 어떻게 배포되는지(환경·빌드 위치별 경로, 직배포 여부, executor) 한눈에. 두 GitLab 파싱 (Phase 5) |

> **제외·이동 (2026-09-10 개편)** — ⑥ PEM(서비스 TLS 인증서) 관리는 **일단 제외**(나중에). 파일 공유 + MD 뷰어는 **별도 프로젝트로 분리** → `../../MoveFILE/파일공유-MD뷰어-프로젝트.md`. 서버 내부 설치 패키지 인벤토리도 나중에(지금은 빌드 설치 항목만). 접속 키(로그인 SSH 키)는 위 ①로 유지.

## 아키텍처 — 중앙(키 없음) + 러너(키 있는 곳) 분리 (2026-09-09 확정)

```
                       ssh                nested ssh
  ┌──────────────┐   (local 키)  ┌─────────┐ (gw 보유 키) ┌──────────┐
  │ local PC(러너) │ ───────────▶ │ GW(점프) │ ──────────▶ │ 대상 서버  │
  │ gw 키·인터넷 O │              │ 서버 키   │             │ Oracle 등 │
  └──────┬───────┘              └─────────┘             └──────────┘
         │ HTTPS
         │ 결과↑ · 기준본↓
  ┌──────▼───────┐
  │ 사내 VM(중앙)  │   웹 UI·API·DB·Git 기준본
  │ 키 없음        │   public IP 불필요, 사내망 전용
  └──────────────┘

  머리(중앙)=명령·기록만, 키 0    /    손(러너)=키 보유·실제 접속
```

- **중앙(사내 VM)**: 웹 UI·API·DB·Git 기준본만. **SSH 키를 일절 저장하지 않음** — 인터넷·public IP 불필요, 사내망 전용
- **러너(CLI)**: 키가 이미 있는 local에서 실행. local 키로 gw 접속 → gw 위에서 gw 보유 키로 대상 서버 nested ssh → 결과를 중앙 API로 업로드, 배포 시엔 기준본 받아 적용 후 보고
- 키 위치 현행 유지(gw 키=local, 서버 키=각 gw), 대상 서버·gw엔 여전히 설치물 없음. Oracle 등 외부 서버는 local이 인터넷 가능하므로 러너가 커버
- 주기 수집: 중앙은 수집 요청 큐만 관리, 러너가 실행. 완전 자동화 필요 시 상시 켜진 관리 PC 1대에 러너 cron 배치
- 스택: 중앙 FastAPI + React + SQLite(→PostgreSQL) / 러너 Python CLI(asyncssh), 러너 인증은 API 토큰
- 보안: 중앙 키 무보관(유출 시 피해=메타데이터 한정), RBAC(admin/operator/viewer), 감사 로그 append-only
- **배포**: 중앙 서비스는 **Docker 컨테이너로 패키징** → `docker compose`(웹 + API + DB)로 실행. 러너는 로컬 CLI(로컬 `~/.ssh` 키 접근 필요)
- **단일 머신은 test 단계뿐**: 지금(개발·test)은 **로컬 1대 = dev·stg·prod** 겸용(`docker compose up -d` = 로컬 상시). 다만 **실제 운영 목표는 중앙(VM) + 러너 분리**이고 거기서 중앙 무키가 진짜 보안이 됨 → 중앙 무키·중앙/러너 split을 **처음부터 유지**(상시 대시보드 vs 온디맨드 수집, test↔real 구조 일치). 지금 구조 그대로 VM 이관 가능

## 기술 선택 노트 (2026-09-10)

**원칙: 코어는 얇게. 무거운 인프라는 "쓰지 말고, 나중에 관리 대상으로 품는다."**

- **내부 스택**: 중앙 FastAPI + React + SQLite(→PostgreSQL) + 러너 Python CLI. 이대로 유지.
- **Redis/Valkey**: 지금은 도입 안 함(수집 큐·라이브 갱신은 DB 테이블/LISTEN-NOTIFY로). 러너 다수·중앙 다중 인스턴스가 되는 **스케일 트리거** 시에만 큐+pub/sub 용도로 도입.
- **Consul / Kong**: 내부 도입 ✗. 노드 에이전트 성격(**agentless 원칙 충돌**) + **BUSL 라이선스** 리스크를 관리도구 안으로 들이는 역설(이 도구가 줄이려는 게 SPOF·라이선스 부담).
- **대신 "관리 대상"으로 (나중에)**: conf 관리를 **대상 타입 플러그인**으로 설계 — 지금은 `file`(nginx.conf 등)만, 나중에 `kong`(Admin API)·`consul-kv`(KV API)를 같은 방식(기준본·diff·드리프트·승인 배포)으로 확장. 별도 트랙(설정 저장소 과제)과 여기서 만난다.
- **적용 시점**: 코어(Phase 0·1·2·4·5)를 먼저 완성하고, 확장 타입·인프라 도입은 그 위에 얹는다.

## 동기화

- **Pull(수집)** — 소스 2종:
  - **빌드/서버(ssh)**: 러너가 큐를 받아 conf + docker builder의 `docker --version` 수집 → 중앙 API 업로드. (서버 내부 설치 패키지·런타임 인벤토리는 나중에)
  - **GitLab repo(API)**: 중앙 VM이 사내망에서 GitLab API 직접 호출(토큰). **repo·center는 두 GitLab 인스턴스**(repo=repo.theloop.co.kr, center=gitlab.center.24x365.online). `.gitlab-ci.yml`(image 태그=빌드 버전)·`Dockerfile`(`FROM`·`RUN apt/npm`=빌드 설치 항목)·`package.json`·`.nvmrc`·`pom.xml` 파싱 → 빌드 버전 + 설치 항목
  - 두 소스 모두 기준본과 diff → 배지, EOL 매칭. (레포 선언본 vs 서버 런타임 불일치도 드리프트로 표시 가능)
- **Push(적용)**: dry-run diff → 승인(prod) → 서버 백업 → 원자적 교체 → 검증(`validate_cmd`, 실패 시 자동 복원) → reload → 기록
- 수집기 정의 예 (서비스 추가 = YAML 1개):

```yaml
# 서버 런타임 소스 (ssh)
name: nginx
source: ssh
version_cmd: "nginx -v 2>&1"
version_regex: "nginx/([0-9.]+)"
conf_paths: [/etc/nginx/nginx.conf, /etc/nginx/conf.d/]
validate_cmd: "nginx -t"
reload_cmd: "systemctl reload nginx"
```

```yaml
# GitLab repo 선언본 소스 (API)
name: backend-stack
source: gitlab
instances: [repo (repo.theloop), center (gitlab.center)]   # 두 GitLab 인스턴스
projects: ["web3/supercycl/*"]                              # 대상 레포 글롭
extract:
  node: ["package.json:engines.node", ".nvmrc"]
  nest: ["package.json:dependencies.@nestjs/core"]
  java: ["pom.xml:java.version", "build.gradle:sourceCompatibility"]
```

## UI — 페이지 구성

멀티 탭 앱 — 대시보드가 랜딩(개요)이고 각 탭에서 상세로 드릴다운. (한 페이지 아님)

```
Control Tower
├─ 대시보드      요약 카드(온라인·드리프트·대기 업데이트·EOL) + 버전 매트릭스 + 최근 작업
├─ 서버         서버·접속키 인벤토리 — 목록·그룹·태그 / 서버 클릭 → 접속키·gw·상태 (키 중심 뷰 토글)
├─ 버전·빌드     빌드 버전 + 빌드 설치 항목 — 대상×버전 매트릭스, EOL 배지
├─ 설정(conf)   기준본 목록 / 서버별 diff / 드리프트 / 배포(push)
├─ 업데이트      서버별 대기 패치(보안 구분) / 그룹 dry-run→적용
├─ CI/CD        서비스별 배포 경로·환경 매트릭스·직배포·executor (Phase 5)
└─ 작업이력      수집·배포 job 로그 + 감사 로그
```

- **드리프트는 별도 탭이 아님** — 대시보드 카드 + 각 페이지(설정·버전)의 배지로 관통.
- **접속키 인벤토리는 '서버' 탭 안** — 서버별 "무슨 키로 들어가나" + "이 키 쓰는 서버?" 키 중심 뷰.
- **탐색 축 2개** — ① 서버 중심(이 서버의 모든 것) ② 관심사 중심(전 서버의 conf/업데이트). 대시보드 카드 클릭 → 관심사 페이지로 드릴다운.

## 로드맵

| Phase | 내용 | 완료 기준 |
|---|---|---|
| 0. 기반 | 서버 인벤토리·그룹/태그, **`~/.ssh/config` 임포트**(서버·gw·접속키 매핑 부트스트랩), 자격증명 참조(별칭) 저장, SSH 연결 테스트 | 실서버 등록·연결 OK + 접속 키 매핑이 화면에 |
| 1. 수집(read-only) | 접속키 인벤토리, 빌드 버전·conf 수집, 통합 대시보드 = **MVP** | 전 서버 접속키·빌드 버전이 화면 하나에 |
| 2. 배포·동기화 | Git 저장소, 변수 치환, 드리프트 뷰, push 파이프라인, 감사 로그 | 배포→검증 실패→자동 롤백 통과 |
| ~~3. 파일·MD~~ | **별도 프로젝트로 분리** → `../../MoveFILE/파일공유-MD뷰어-프로젝트.md` | (제외) |
| 4. 알림·운영 | 드리프트 알림, 업데이트 적용, EOL 매칭 | 그룹 업데이트 1회 성공 |
| 5. CI/CD 현황 | 두 GitLab(repo·center) 파이프라인 파싱, 서비스별 배포 경로·환경 매트릭스, 직배포·executor 이관 대시보드 | 전 서비스 배포 경로·이관 상태가 한 화면에 |

## Phase 5 — CI/CD 배포 현황 관리 (2026-09-10 정식 편입)

> repo(`repo.theloop.co.kr`)와 center(`gitlab.center.24x365.online`)는 **두 개의 GitLab 인스턴스**이고 supercycl은 repo→center 이관 중.
> (앞의 '버전 관리'에서 repo·center는 프로젝트명이 아니라 이 두 GitLab. config는 center 인프라 repo)

**Phase 5로 정식 편입**(2026-09-10). 버전 관리·GitLab 연동 위에 얹는다. 관리 대상:

- **서비스별 배포 경로** — repo CI → center CI(push_src) → 이미지 빌드/배포 잡의 연결 상태
- **환경 매트릭스** — dev·stg·preview·lab·prod 별 배포 방식·대상 서버(IP)
- **직배포 탐지** — scp standalone 직배포(aggregator dev/stg, brandsite, youthmeta-mobile 등) = 이관 대상 플래그
- **executor 유형** — shell(`gitrun-cycl-brand`) / docker(`repo-runner`) + docker 전환 대상
- **이관 준비 상태** — 서비스별 ✅/⚠️/❌
- **고아·불명 서비스** — 원본 repo 부재(sync_was 404) 등 존폐 확인 대상

상세 조사 원본(2026-08-27 라이브 API, 미결 질문 8개 포함): `supercycl-CICD-현황.md`

## 추후 진행 (별도 트랙) — 런타임 설정·정책 저장소 중앙화

Control Tower(운영 관리·관측 도구)와 **별개 트랙**인 인프라 과제. 서비스가 런타임에 읽는
설정·시크릿·ratelimit 카운터의 **중앙 저장소 선정·HA 설계**(Redis→Valkey, Vault→OpenBao,
Consul/etcd, Kong 서비스단 ratelimit). 상세: `관련과제-설정정책중앙화.md`(docs/ 내). **코어 완성 이후 추후 진행.**

**접점** — ① 설정이 파일→중앙 저장소로 옮겨가면 Control Tower의 conf 관리 대상 범위가 달라짐
② Control Tower의 **버전/패키지 인벤토리가 라이선스 노출(Redis SSPL·Vault/Consul BUSL) 조사**를
그대로 만들어줌 → 이 과제의 근거 데이터로 재활용. 제품 통합 여부는 추후 결정.

## 열린 질문

**A. Phase 0 착수 전 (전제 조건)**

1. **서버 규모·OS** — ✅ Ubuntu, 서버 상당히 많을 예정 → apt 기준, 대규모이므로 gw별 동시성 제한·연결 풀링이 중요
2. **러너 위치·키** — ✅ 결정: 키를 local에만 두고 **러너도 local에서 실행**. 자동 주기 수집은 PC가 켜져 있을 때만(트레이드오프 수용). 러너는 15개 gw 전부에 도달 가능해야 함. 향후 상시 자동화가 꼭 필요해지면 상시 관리 PC/러너를 추가 가능
3. **gw 구조·MFA** — ✅ gw 15개, MFA 거의 없음 → 대부분 자동 수집 가능, MFA 있는 소수만 수동 처리
4. **GitLab** — ✅ self-hosted 전환 중, 토큰 발급 가능 → 중앙 VM이 사내망에서 API 직접 호출(전환 완료 후 연동)
5. **빌드 환경 위치** — 🔎 잠정 (b) 별도 빌드 전용 서버 → 그 서버에 SSH로 node·java·docker 버전 수집. 빌드 위치·docker builder 머신 위치는 사용자 확인 예정

**B. 해당 Phase에서 정하면 되는 것**

6. 폐쇄망 여부 — EOL 매칭·알림 채널·패키지 미러 방식이 달라짐 (Phase 1·4)
7. conf 관리 — 대상 파일 목록 + 배포(push)까지 갈지, prod 승인 정책 (Phase 2)
8. ~~PEM~~ — **제외(2026-09-10)**: 서비스 TLS 인증서 관리는 이번 스코프에서 뺌
9. update — 대기 목록만 보여줄지 vs 실제 적용까지 (Phase 4)
10. ~~파일 공유~~ — **별도 프로젝트로 분리**(`../../MoveFILE/파일공유-MD뷰어-프로젝트.md`)
11. 로그인·사용자 — 사내 SSO/LDAP 연동 vs 자체 계정, 사용자 수(RBAC 수준) (Phase 0)
