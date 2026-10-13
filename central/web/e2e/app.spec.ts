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

  // 버전(선언본) 시드: aggregator_web repo node/nest
  await api.post('/api/versions/repo-snapshots', {
    data: {
      snapshots: [
        { repo: 'aggregator_web', tool: 'node', version: '20.11' },
        { repo: 'aggregator_web', tool: 'nest', version: '10.3' },
      ],
    },
  })

  // CI/CD 시드(소스 무관 인제스트): admin 서비스 파이프라인 성공
  await api.post('/api/cicd/targets', { data: { service: 'admin', project: 'group/aggregator-admin' } })
  await api.post('/api/cicd/status', {
    data: { statuses: [{ service: 'admin', has_cicd: true, status: 'success', ref: 'main', web_url: 'http://gl/p/1' }] },
  })

  // 서비스 비교표 시드(러너 shape 역할): node 18 vs 20 → 18 이 빨간 칸
  const shape = await api.post('/api/cicd/shape', {
    data: {
      shapes: [
        { service: 'shop web', group: 'shop', data: { runtime: 'node', runtime_version: '18', deploy: { dev: { path: 'direct', by: 'repo', manual: false } }, startup: true } },
        { service: 'shop admin', group: 'shop', data: { runtime: 'node', runtime_version: '20', deploy: { dev: { path: 'image', manual: false } }, startup: false } },
      ],
    },
  })
  expect(shape.ok(), await shape.text()).toBeTruthy()

  // center config 시드(러너 shape 역할): 구형(start.sh) / 완료(CMD) + compose 이사 전
  const cfg = await api.post('/api/cicd/config', {
    data: {
      items: [
        { path: 'shop/web', data: { runtime: 'node', runtime_version: '18', base_image: 'infra/nodejs', base_tag: 'v18', start: 'start.sh', start_files: ['node-startup.sh'], state: 'legacy', compose: { dev: 'mount' } } },
        { path: 'shop/api', data: { runtime: 'node', runtime_version: '22', base_image: 'node', base_tag: '22-slim', start: 'dockerfile', start_files: [], state: 'done', compose: { dev: 'command' } } },
      ],
    },
  })
  expect(cfg.ok(), await cfg.text()).toBeTruthy()

  await api.dispose()
})

test('서버 인벤토리에 임포트된 서버가 보인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '서버' }).click()
  await expect(page.getByRole('heading', { name: /서버 · 접속키/ })).toBeVisible()
  const list = page.locator('table').first() // 같은 탭 아래 /etc 설정 파일 표에도 서버 이름이 나옴
  await expect(list.getByText('web-01')).toBeVisible()
  await expect(list.getByText('web-02')).toBeVisible()
  await expect(page.getByText('prod', { exact: true })).toBeVisible() // 그룹 태그(드롭다운 'prod (1)' 와 구분)
  await expect(page.getByText('edge', { exact: true })).toBeVisible() // 태그
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

test('대시보드가 실집계를 보여준다', async ({ page }) => {
  await page.goto('/')
  // 기본 탭=대시보드. 서버 2대 임포트·연결테스트 미실행 → 온라인 0/2
  await expect(page.getByText('0/2')).toBeVisible()
  await expect(page.getByText('수집 현황')).toBeVisible()
})

test('OS 패치·작업이력 탭 오른쪽에 작업이력이 쌓인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'OS 패치·작업이력' }).click()
  await expect(page.getByRole('heading', { name: '작업이력 (전체)' })).toBeVisible()
  // 시드가 import·conf 수집·updates 수집을 수행 → 감사 로그로 표시
  await expect(page.getByText('서버 임포트')).toBeVisible()
  await expect(page.getByText('업데이트 수집')).toBeVisible()
})

test('빌드·배포 탭에 툴체인·선언본 버전이 보인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포' }).click()
  await expect(page.getByText('20.11.1')).toBeVisible() // 빌드 서버 툴체인
  await expect(page.getByText('aggregator_web')).toBeVisible() // GitLab repo 선언본
})

test('빌드·배포 탭에 파이프라인 상태가 보인다', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포' }).click()
  await expect(page.getByRole('link', { name: 'admin', exact: true })).toBeVisible()
  await expect(page.getByText('성공')).toBeVisible()
})

test('빌드·배포 탭 서비스 비교표 — 오래된 버전은 빨간 칸', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포' }).click()
  await expect(page.getByText('shop admin')).toBeVisible()
  await expect(page.getByText('⚠ node 18')).toHaveClass(/ver--old/)
  await expect(page.locator('table.grid--nowrap').getByText('node 20', { exact: true })).not.toHaveClass(/ver--old/)
  await expect(page.locator('table.grid--nowrap').getByText('repo', { exact: true })).toBeVisible()
  await expect(page.getByText('표 읽는 법')).toBeVisible()
})

test('빌드·배포 탭에서 서비스(대상) 추가', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '빌드·배포' }).click()
  await page.getByPlaceholder('서비스 이름').fill('billing')
  await page.getByPlaceholder('GitLab 프로젝트 (group/repo 또는 id)').fill('group/billing')
  await page.getByRole('button', { name: '서비스 추가' }).click()
  await expect(page.getByText('billing', { exact: true })).toBeVisible() // 새 대상 행(상태 없음)
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

test('config 탭 — 실행 명령 위치·상태·compose 이사 + 새로고침', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'config' }).click()
  await expect(page.locator('table.grid--nowrap').getByText('shop', { exact: true })).toBeVisible()
  await expect(page.getByText('⚠ node 18')).toHaveClass(/ver--old/)
  await expect(page.locator('table.grid--nowrap').getByText('구형', { exact: true })).toBeVisible()
  await expect(page.getByText('dev 이사 전')).toBeVisible()
  await expect(page.getByText('dev 이사 완료')).toBeVisible()
  await page.getByRole('button', { name: 'config 폴더 새로고침' }).click()
  await expect(page.getByText(/데이터 기준/)).toBeVisible()
})
