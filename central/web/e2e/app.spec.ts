import { expect, request, test } from '@playwright/test'

const API = process.env.CT_E2E_API || 'http://127.0.0.1:8099'
const TOKEN = 'e2e-web-token'
const CONF_PATH = '/etc/nginx/nginx.conf'

// API 에 직접 시드(러너 역할): 서버 임포트 → conf 대상·스냅샷 → web-01 을 기준본으로 채택.
// 결과적으로 web-01=synced, web-02=drift 가 되어야 한다.
test.beforeAll(async () => {
  const api = await request.newContext({
    baseURL: API,
    extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` },
  })

  const imp = await api.post('/api/servers/import', {
    data: {
      servers: [
        { hostname: 'web-01', ip: '10.0.0.1', ssh_user: 'deploy', credential_alias: 'id_rsa', access_control: 'ncloud' },
        { hostname: 'web-02', ip: '10.0.0.2', ssh_user: 'deploy', credential_alias: 'id_rsa' },
      ],
    },
  })
  expect(imp.ok(), await imp.text()).toBeTruthy()

  const servers: Array<{ id: number; hostname: string }> = await (await api.get('/api/servers')).json()
  const id = (h: string) => servers.find((s) => s.hostname === h)!.id

  // 그룹·태그 시드: web-01 을 prod 그룹 + edge 태그로
  const gid = (await (await api.post('/api/groups', { data: { name: 'prod' } })).json()).id
  await api.post(`/api/servers/${id('web-01')}/meta`, { data: { group_id: gid, tags: ['edge'] } })

  await api.post('/api/conf/targets', { data: { path: CONF_PATH } })
  await api.post('/api/conf/snapshots', {
    data: {
      snapshots: [
        { server_id: id('web-01'), path: CONF_PATH, content: 'gzip on;\nworker_processes 4;\n' },
        { server_id: id('web-02'), path: CONF_PATH, content: 'worker_processes 4;\n' }, // gzip 누락 → drift
      ],
    },
  })
  const adopt = await api.post('/api/conf/baselines/adopt', { data: { path: CONF_PATH, server_id: id('web-01') } })
  expect(adopt.ok(), await adopt.text()).toBeTruthy()

  // 업데이트(apt) 실데이터 시드: web-01 은 대기 2건(보안 1), web-02 는 0건
  await api.post('/api/updates/snapshots', {
    data: {
      snapshots: [
        {
          server_id: id('web-01'),
          packages: [
            { name: 'openssl', from: '3.0.2', to: '3.0.13', security: true },
            { name: 'nginx', from: '1.18.0', to: '1.24.0', security: false },
          ],
        },
        { server_id: id('web-02'), packages: [] },
      ],
    },
  })

  // 버전(툴체인) 시드: web-01 node/docker
  await api.post('/api/versions/snapshots', {
    data: {
      snapshots: [
        { server_id: id('web-01'), tool: 'node', version: '20.11.1' },
        { server_id: id('web-01'), tool: 'docker', version: '24.0.7' },
      ],
    },
  })

  // 서비스 비교표 시드(러너 shape 역할): node 18 vs 20 → 18 이 빨간 칸
  const shape = await api.post('/api/cicd/shape', {
    data: {
      shapes: [
        {
          service: 'shop web', group: 'shop',
          data: {
            runtime: 'node', runtime_version: '18', deploy: { dev: { path: 'direct', by: 'repo', manual: false } }, startup: true, host: 'gitlab',
            // repo 보기: 빌드 node 20(CI 이미지) · 코드 node 22(.nvmrc) · 실행 node 18 → 셋 다 다름
            repo: { project: 'team/shop-web', read: true, build: [{ runtime: 'node', version: '20', image: 'node:20-slim', jobs: ['build'] }], code: { node: '22', node_from: '.nvmrc', node_rule: 'exact' } },
          },
        },
        {
          service: 'shop admin', group: 'shop',
          data: {
            runtime: 'node', runtime_version: '20', deploy: { dev: { path: 'image', manual: false } }, startup: false, host: 'gitlab',
            // 빌드·배포 버전: prod 는 v2.0.0 을 빌드해 두고 v1.9.0 이 배포돼 있음
            versions: {
              build: { dev: { version: 'v2.0.0', tag: 'dev-admin-v2.0.0', at: '2026-10-12T00:00:00Z', job: 21, side: 'center' }, prod: { version: 'v2.0.0', tag: 'prod-admin-v2.0.0', at: '2026-10-13T00:00:00Z', job: 23, side: 'center' } },
              deploy: { dev: { version: 'v2.0.0', tag: 'dev-admin-v2.0.0', at: '2026-10-12T01:00:00Z', job: 22, side: 'center' }, prod: { version: 'v1.9.0', tag: 'prod-admin-v1.9.0', at: '2026-10-01T00:00:00Z', job: 15, side: 'center' } },
            },
            // job 로그로 확정한 executor — 펼치면 job | image | 러너, 아래 러너 표에 등록된 이름
            executor_center: {
              value: 'docker', guess: false, tags: ['builder', 'deployer'], counts: { shell: 1, docker: 2 },
              groups: [
                { tag: 'builder', value: 'shell', guess: false, why: 'job 로그 #11', jobs: ['build'], images: {}, runner_name: 'build-host-01' },
                { tag: 'deployer', value: 'docker', guess: false, why: 'job 로그 #12', jobs: ['deploy-dev', 'deploy-prod'], images: { 'deploy-dev': 'deploy-image:latest', 'deploy-prod': 'deploy-image:latest' }, runner_name: 'gw-dev-01' },
              ],
            },
          },
        },
        // GitHub 에서 빌드하는 서비스 — 그룹 칸에 [GitHub], config 표 아래 '여기 없음'
        { service: 'blog web', group: 'blog', data: { deploy: { dev: { path: 'image', by: 'compose', manual: null } }, host: 'github' } },
      ],
    },
  })
  expect(shape.ok(), await shape.text()).toBeTruthy()

  // center config 시드(러너 shape 역할): 구형(start.sh) / 완료(CMD) + start.sh 형태 shell·compose
  const cfg = await api.post('/api/cicd/config', {
    data: {
      items: [
        {
          path: 'shop/web',
          data: {
            runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18', start: 'start.sh', start_files: ['node-startup.sh'], state: 'legacy',
            compose: { dev: 'mount' }, code: { node: '22', node_from: '.nvmrc', node_rule: 'exact' }, group: 'shop', config_repo: 'shop/config',
            compose_src: { dev: { kind: 'ssh', auto: true, via: 'gw-dev', where: 'gw-dev → web-dev:/app/web-shop/docker-compose.yml' } },
            compose_miss: { prod: { state: 'fail', reason: 'SSH 로 못 읽음 — gw-prod → web-prod (Host key verification failed.)' } },
            deploy_envs: ['dev', 'prod'],
          },
        },
        { path: 'shop/api', data: { runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done', compose: { dev: 'command' }, group: 'shop', config_repo: 'shop/config' } },
        { path: 'shop/old', data: { state: 'none', merged_into: 'shop/api', group: 'shop', config_repo: 'shop/config' } },
      ],
    },
  })
  expect(cfg.ok(), await cfg.text()).toBeTruthy()

  await api.dispose()
})

test('서버 탭 = 누가 · 어디로 — 금고 연결 전이면 빈 목록이 아니라 "연결하지 않았어요", 예전 서버 목록(IP·접속키)은 안 보임', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '서버' }).click()
  await expect(page.getByRole('heading', { name: '누가 · 어디로' })).toBeVisible()
  await expect(page.getByText(/금고 목록에 아직 연결하지 않았어요/)).toBeVisible() // CT_INVENTORY_MODE 기본 off
  await expect(page.getByPlaceholder('서버 · IP · user 검색')).toHaveCount(0)
  // 목록 고치기는 기본 꺼짐(CT_INVENTORY_EDIT) — 버튼도 없고, API 로 바로 보내도 '꺼져 있어요'
  await expect(page.getByRole('button', { name: '목록 고치기' })).toHaveCount(0)
  const put = await page.request.put('/api/inventory/dev/shop', { data: { version: 1, servers: {} } })
  expect(put.status()).toBe(403)
  expect((await put.json()).detail).toContain('꺼져 있어요')
})

test('서버 탭의 /etc 설정 파일 섹션에서 동기화·드리프트가 보인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '서버' }).click()
  await expect(page.getByRole('heading', { name: '서버 설정 파일 (/etc)' })).toBeVisible()
  await expect(page.getByText('동기화됨', { exact: true })).toBeVisible()
  await expect(page.getByText('드리프트', { exact: true })).toBeVisible()
})

test('OS 패치·작업이력 탭에서 서버 행을 열면 패키지가 보인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'OS 패치·작업이력' }).click()
  // web-01 은 기본 펼침
  await expect(page.getByText('openssl').first()).toBeVisible()
})

test('대시보드가 실집계를 보여준다 — 탭 순서 서버 → 접속 기록 → config → 빌드·배포', async ({ page }) => {
  await page.goto('/')
  // 기본 탭=대시보드. 서버 탭은 IdP 연동 후 연결 자리 → 서버 카드는 /etc 설정 드리프트만(온라인 서버 없음)
  await expect(page.locator('nav.sub-nav button')).toHaveText(['대시보드', '서버', '접속 기록', 'config', '빌드·배포', 'OS 패치·작업이력'])
  await expect(page.locator('a.stat .stat-tab')).toHaveText(['서버', 'config', 'config', '빌드·배포', 'OS 패치·작업이력'])
  await expect(page.getByText('온라인 서버')).toHaveCount(0)
  await expect(page.getByText('수집 현황')).toBeVisible()
})

test('접속 기록 탭 — 로그인 정보(그룹)를 모르면 기록 대신 "몰라 보여 줄 수 없어요"(운영자만 보는 기록)', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '접속 기록' }).click()
  await expect(page.getByRole('heading', { name: '접속 기록' })).toBeVisible()
  await expect(page.getByText(/로그인 정보\(그룹\)를 몰라 보여 줄 수 없어요/)).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
})

test('맨 위 버전 — 화면 프록시(/api)로 닿고, 반영할 때 안 넣었으면 "버전 모름(dev)"', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.global-nav .meta')).toHaveText(/^버전 모름\(dev\) · \d\d\/\d\d \d\d:\d\d 시작$/)
})

test('OS 패치·작업이력 탭 오른쪽에 작업이력이 쌓인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'OS 패치·작업이력' }).click()
  await expect(page.getByRole('heading', { name: '작업이력 (전체)' })).toBeVisible()
  // 시드가 import·conf 수집·updates 수집을 수행 → 감사 로그로 표시
  await expect(page.getByText('서버 임포트')).toBeVisible()
  await expect(page.getByText('업데이트 수집')).toBeVisible()
})

test('빌드·배포 탭 서비스 비교표 — 배포 방식·범례', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포' }).click()
  await expect(page.locator('td.svc-cell', { hasText: 'shop admin' })).toBeVisible() // 러너 표에도 서비스 이름이 나와서 칸으로 좁힘
  await expect(page.locator('table.grid--nowrap').getByText('repo', { exact: true })).toBeVisible()
  await expect(page.getByText('표 읽는 법')).toBeVisible()
})

test('서버 탭 /etc 설정 적용: 계획 → 승인 (서버 쓰기 없음)', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '서버' }).click()
  // web-02 가 드리프트 → [적용 계획]
  await page.getByRole('button', { name: '적용 계획' }).click()
  await expect(page.getByText('적용 대기 · 이력')).toBeVisible()
  // 승인 게이트
  await page.getByRole('button', { name: '승인' }).click()
  await expect(page.getByText('승인됨')).toBeVisible()
})

test('config 탭 — 처음 실행할 명령(이미지·서버)·정리할 것 (↻ 대신 [다시 수집])', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'config' }).click()
  await page.getByRole('tab', { name: 'center' }).click() // 기본은 repo 보기
  await expect(page.locator('table.grid--nowrap').getByText('shop', { exact: true })).toBeVisible()
  await expect(page.getByText('⚠ node 18')).toHaveClass(/ver--old/)
  const table = page.locator('table.grid--nowrap')
  await expect(table.getByText('CMD 로 옮기기')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'dev', exact: true })).toBeVisible() // (서버) 환경 열
  await expect(table.getByText('서버 compose')).toBeVisible() // shop/api dev: 서버 compose 의 command:
  await expect(page.getByText(/데이터 기준/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'config 폴더 새로고침' })).toHaveCount(0) // [다시 수집] 과 겹쳐 뺌
})

test('빌드·배포 — 그룹 칸 GitLab/GitHub, executor 펼치면 job | image | 러너, 러너 표', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포', exact: true }).click()
  const table = page.locator('table.grid--nowrap')
  await expect(table.locator('td.grp-cell', { hasText: 'shop' })).toContainText('GitLab')
  await expect(table.locator('td.grp-cell', { hasText: 'blog' })).toContainText('GitHub')
  // executor ▸ 펼치기 — 열 맞춘 작은 표
  await page.getByLabel('center 나머지 2개 펼치기').click()
  const mini = table.locator('details.exec-more[open] table.mini-table') // 닫힌 줄의 표도 DOM 엔 있어서 펼친 것만
  await expect(mini.locator('th')).toHaveText(['job', 'image', '러너'])
  await expect(mini.locator('tbody tr').first()).toContainText('deploy-dev')
  await expect(mini.locator('tbody tr').first()).toContainText('deploy-image:latest')
  // 러너 표: 태그마다 방식 · 확인 근거 · 등록된 이름
  await expect(page.getByRole('heading', { name: '러너' })).toBeVisible()
  const runners = page.locator('.section-head', { hasText: '러너' }).locator('+ .card')
  await expect(runners.locator('tr', { hasText: 'builder' })).toContainText('확정 · job 로그 #11')
  await expect(runners.locator('tr', { hasText: 'builder' })).toContainText('build-host-01')
  // 표 읽는 법은 기본 접힘 → 펼치면 칸 | 뜻
  const legend = page.locator('details.legend')
  await expect(legend).not.toHaveAttribute('open', '')
  await legend.locator('summary').click()
  await expect(legend.locator('.legend-grid > dt').first()).toHaveText('빌드 버전 · 배포 버전') // 칸 순서대로
})

test('빌드·배포 — 빌드 버전 · 배포 버전 칸, 배포가 밀린 환경은 빨간 칸', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: '빌드 버전' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '배포 버전' })).toBeVisible()
  const admin = page.locator('table.grid--nowrap tr', { hasText: 'admin' })
  await expect(admin.getByText('⚠ v1.9.0')).toHaveClass(/ver--old/) // 빌드 v2.0.0 · 배포 v1.9.0
  await expect(page.getByText(/배포 안 된 빌드 1곳/)).toBeVisible()
  await expect(page.locator('table.grid--nowrap tr', { hasText: 'blog' }).getByText('모름')).toHaveCount(0) // GitHub = —
})

test('config — center / repo 보기: repo 는 빌드 · 코드 · 실행 비교', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'config' }).click()
  await expect(page.getByRole('tab', { name: 'repo' })).toHaveAttribute('aria-selected', 'true') // 처음엔 repo(흐름 순서 repo → center)
  const table = page.locator('table.grid--nowrap')
  const web = table.locator('tr', { hasText: 'team/shop-web' })
  await expect(web).toContainText('node 20') // 빌드(CI 이미지)
  await expect(web).toContainText('node 22') // 코드(.nvmrc)
  await expect(web.locator('.badge--warn')).toHaveText(['⚠ 빌드≠코드', '⚠ 빌드≠실행', '⚠ 코드≠실행'])
  await expect(page.locator('.note-line', { hasText: 'GitLab repo 가 없어' })).toContainText('blog web')
  // 고른 보기는 기억 — center 로 바꾸고 다른 탭에 갔다 와도 center
  await page.getByRole('tab', { name: 'center' }).click()
  await page.getByRole('button', { name: '빌드·배포', exact: true }).click()
  await page.getByRole('button', { name: 'config' }).click()
  await expect(page.getByRole('tab', { name: 'center' })).toHaveAttribute('aria-selected', 'true')
})

test('config — ▸ 줄 펼치면 환경별 표, 그룹 칸 config repo, GitHub 서비스 안내', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'config' }).click()
  await page.getByRole('tab', { name: 'center' }).click()
  const table = page.locator('table.grid--nowrap')
  await expect(table.locator('td.grp-cell', { hasText: 'shop' })).toContainText('shop/config')
  await expect(page.locator('.note-line')).toContainText('blog web')
  await page.getByRole('button', { name: 'shop/web 환경별 자세히' }).click()
  const detail = table.locator('tr.row-detail table.mini-table')
  await expect(detail.locator('th')).toHaveText(['환경', '처음 실행할 명령', '어디서 읽었나', '위치 · 이유'])
  await expect(detail.locator('tbody tr', { hasText: 'dev' })).toContainText('gw-dev → web-dev')
  await expect(detail.locator('tbody tr', { hasText: 'prod' })).toContainText('못 읽음')
  await expect(detail.locator('tbody tr', { hasText: 'stg' })).toContainText('이 환경엔 배포 안 함')
  // 합쳐진 폴더는 흐린 줄 + 합쳐짐
  await expect(table.getByText('합쳐짐 → shop/api')).toBeVisible()
})

test('[다시 수집] — 수집기가 꺼져 있으면 버튼도 꺼짐, 켜지면 켜짐 → 요청 → 수집기가 처리 → 완료', async ({ page }) => {
  test.setTimeout(60_000)
  const collector = await request.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${TOKEN}` } })
  const claim = async () => (await (await collector.post('/api/collect/claim', { data: { kind: 'shape', collector: 'e2e-collector', mode: 'gitlab' } })).json()).request
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포', exact: true }).click()
  const button = page.locator('.collect button')
  // e2e 에는 수집기가 없음 → 버튼 꺼짐(누르면 영원히 '요청됨'이 되니까)
  await expect(page.locator('.collect-state')).toHaveText(/^수집기 꺼짐 · 데이터 기준 /)
  await expect(button).toBeDisabled()
  await expect(page.locator('.section-asof')).toHaveCount(0) // 시각은 버튼 옆 한 곳에만
  // 수집기가 켜짐(5초마다 확인하는 것처럼 한 번 확인) → 화면이 10초 안에 알아채고 버튼을 켬
  expect(await claim()).toBeNull()
  await expect(button).toBeEnabled({ timeout: 15_000 })
  await button.click()
  await expect(page.locator('.collect-state')).toHaveText('요청됨 — 곧 시작')
  await expect(page.getByRole('button', { name: '수집 중…' })).toBeDisabled() // 연타 방지
  // 수집기가 가져가서 끝냄 → 화면은 완료 + 표를 새로 불러옴
  const req = await claim()
  expect(req.status).toBe('running')
  await expect(page.locator('.collect-state')).toHaveText('수집 중 — GitLab 을 다시 읽는 중')
  await collector.post(`/api/collect/requests/${req.id}/finish`, { data: { ok: true, message: '서비스 3개' } })
  await expect(page.locator('.collect-state')).toHaveText(/^데이터 기준 .* · 방금 갱신$/)
  await expect(button).toHaveText('다시 수집')
  await collector.dispose()
})

test('대시보드 카드를 누르면 그 탭으로 · 작업이력은 페이지로', async ({ page }) => {
  await page.goto('/')
  await page.locator('a.stat', { hasText: '파일 복사 배포' }).click()
  await expect(page.getByRole('heading', { name: '빌드 · 배포' })).toBeVisible()
  await page.getByRole('button', { name: 'OS 패치·작업이력' }).click()
  const pager = page.getByRole('navigation', { name: '작업이력 페이지' })
  await expect(pager).toContainText(/^1–\d+ \/ \d+/)
  await expect(pager.getByRole('radio', { name: '20개' })).toBeVisible()
})
