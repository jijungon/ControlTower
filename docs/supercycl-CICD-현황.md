# supercycl 서비스별 CI/CD 현황 (repo → center 이관 준비)

> Control Tower 참고 자료. Control Tower가 **CI/CD 배포 현황도 관리 대상**으로 삼기를 원함(2026-09-10 기록).
> 상세는 PLAN.md의 "향후 관리 후보 — CI/CD 배포 현황" 참고.

- 조사일: 2026-08-27 / 출처: repo.theloop.co.kr(web3/supercycl) · gitlab.center.24x365.online(supercycl) **라이브 API** (로컬 클론은 라이브보다 뒤처져 있어 배제)
- 표기: `push_src` = repo CI가 빌드 산출물을 center repo에 commit+tag → center `build-image`(도커 이미지 빌드+push) 트리거. ✅ base 구성(repo→center) 완료 / ⚠️ 부분 / ❌ 미적용

## 1. 서비스별 현황표

| 서비스 (center) | repo (theloop, web3/supercycl/…) | repo CI: 빌드·배포 경로 | center CI: 이미지·배포 | repo executor | 상태 |
|---|---|---|---|---|---|
| **admin** | `aggregator/prod/aggregator-admin` (모노레포 web+was) | build → push_src (prod만; dev/stg 환경 자체가 없음) | build-image + deploy-prod(자동) + rollback | `repo-runner` (docker) | ✅ |
| **aggregator** | `aggregator/prod/aggregator_web` (web+mapp) + `aggregator/prod/aggregator_was` (was) | **web/mapp: dev·lab 직배포**(scp standalone, 144.24.73.187), **stg 직배포**(10.87.1.129, 러너태그 `gitrun-cycl-stage`), preview·prod만 push_src / **was: dev는 빌드만**(배포 잡 없음), stg·prod push_src | build-image(전 env) / deploy-dev·stg 잡은 있으나 **서버 변수 주석 처리**, preview·prod manual(+ratelimit scale 연동, update-env) | `gitrun-cycl-brand` (shell) | ❌ dev/stg 직배포 — **핵심 이관 대상** |
| **brandsite** | `brandsite/brandsite_web` (web만; was 분기는 데드코드) | **dev 직배포**(158.180.75.57), **stg 직배포**(168.107.52.112) + stg·prod push_src | **build-image만** (deploy 스테이지 없음) | `gitrun-cycl-brand` (shell) | ⚠️ dev/stg 직배포, prod 배포 잡도 center에 없음(수동?) |
| **chat** | `aggregator/prod/chat-service` (모노레포 web+was) | build(typecheck·test 게이트) → push_src (dev·prod 전부) | build-image + deploy dev(자동, 10.88.20.5)·stg(자동, 서버 `10.87.` **미완성 placeholder**)·prod(manual, 10.89.2.67) + rollback | `repo-runner` (docker) | ✅ (stg 서버만 미지정) |
| **csbot** | `aggregator/prod/cs-bot` | build(버전 게이트) → push_src (dev·prod 전부) | build-image + deploy dev·prod(자동) + rollback | `repo-runner` (docker) | ✅ |
| **events** | web: `aggregator/prod/events/front-end` / was: `aggregator/prod/events/youthmeta-was` | 둘 다 build → push_src (**전 env**: dev·stg·preview·prod, 직배포 없음) | build-image + deploy dev·stg(자동), preview·prod(manual) + rollback | web: `gitrun-cycl-brand` (shell) / was: `repo-runner` (docker) | ✅ 흐름 / ⚠️ web executor만 전환 대상 |
| **account-sync** | `aggregator/prod/exchange-account-sync` | build → push_src (dev·stg·prod, web\|app\|was 전부) | build-image + deploy dev·stg(자동, acmgr+acsync 통합서버), prod(manual, acmgr/acsync 분리) + rollback | `repo-runner` (docker) | ✅ |
| **pnl** | `aggregator/prod/pnl_was` (java) | build(dev·stg·prod) → push-src **stg·prod만** (**dev는 jar 빌드만 하고 끝**) | build-image / deploy-dev·stg 잡은 있으나 **서버 변수 주석 처리**, prod(manual) + rollback | `gitrun-cycl-brand` (shell) | ⚠️ dev 배포 경로 불명 + shell |
| **sync_was** | `aggregator/prod/sync_was` — **404 (삭제/이관/권한없음)** ← center README에 origin으로 명시 | 조회 불가 | build-image(**was/src 소스 복사 방식** — 빌드 산출물이 아닌 소스가 center repo에 있음) + update-env(manual). deploy 스테이지 없음 | - | ❓ 원본 repo 부재 — 서비스 존속 여부 확인 필요 |
| **youthmeta-mobile** | `aggregator/prototype/youthmeta_mobile` (SERVICE_INFO로 확정) | **dev 직배포**(129.154.52.213) + **prod 직배포**(10.89.1.249, 10.89.1.12). **push_src 통째로 주석 처리** → center로 아무것도 안 감 | build-image(prod-web만) — 현재 트리거 없음(사문화) | `gitrun-cycl-brand` (shell) | ❌ dev/prod 전부 직배포 — 이관 대상 |

- 그룹 밖 참고: **thematic-vault** — repo `web3/supercycl/thematic-vault` → center **`thematicvault/thematic-vault`**(supercycl 그룹 아님), 신형 하네스(`repo-runner`, dev·prod push_src). 스코프 포함 여부는 질문 6.
- 조사 제외(서비스 아님): prototype 3종(aggregator_web·aggregator_web_next·testcase_manager), 라이브러리(gate-api-java·okx-api-java), 도구(toolkit·claude-for-funnel-mobile·pnl-was-tester·resource), community-manager(오늘 생성·CI 없음), center 인프라(config·iac·ratelimit-*)

## 2. 미확정 사항 (질문)

1. **sync_was**: theloop 원본(`aggregator/prod/sync_was`)이 404. 서비스가 아직 살아있는지, exchange-account-sync(account-sync)로 대체된 건지?
2. **youthmeta-mobile**: prototype 그룹 repo가 원본으로 확인됨. 서비스 존속·이관 대상인지, 정리(폐기) 대상인지?
3. **aggregator dev-was / pnl dev-was**: repo CI가 dev 태그에서 빌드만 하고 배포·push가 없음. dev WAS는 수동 배포인지?
4. **gitrun-cycl-stage** 러너: 그룹 러너 목록에 안 보임 (프로젝트 전용 러너? 삭제됨?). aggregator stg 직배포가 지금도 동작하는지?
5. **brandsite prod**: center에서 이미지 빌드까지만 하고 deploy 잡이 없음. prod 배포는 서버에서 수동 compose인지?
6. **thematic-vault**: center 그룹이 `thematicvault`로 별도 — 이번 이관 스코프에 포함?
7. **executor 추정 확인**: `gitrun-cycl-brand`=shell, `repo-runner`=docker 맞는지 (API 미노출로 정황 추정).
8. **lab / preview** 환경: aggregator에만 존재 — 이관 설계에 포함할지?

## 부록: executor 참고 (최소)

- theloop `gitrun-cycl-brand` (id85, okrr-cycl-gw 10.89.0.223 — center PROD gw와 동일 호스트) = **shell 추정**. 사용 CI 6개 = docker 전환 대상: aggregator_web, aggregator_was, brandsite_web, pnl_was, events/front-end, youthmeta_mobile
- theloop `repo-runner` (id96, akrr-gitlab01) = **docker 추정**. 신형 CI 사용: aggregator-admin, chat-service, cs-bot, exchange-account-sync, youthmeta-was, thematic-vault
- center `builder`(id1) = **shell**(설명에 명시) — 모든 center build-image가 사용 / `builder-docker`(id14) = **docker**, 등록만 되고 미사용
- ※ GitLab API는 executor를 노출하지 않음 → shell/docker는 CI 정황 추정 (질문 7)
