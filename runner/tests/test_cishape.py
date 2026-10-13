"""비교표 판독기(cishape) — 실제 파일 모양을 본뜬 가짜 CI/Dockerfile/compose 로 검증."""
from runner.cishape import (
    analyze_ci,
    analyze_compose,
    analyze_dockerfile,
    build_row,
    detect_runtime,
    parse_targets,
    split_image,
)

# 구형: repo 에서 dev/stg 는 서버로 scp(직배포), preview/prod 는 center 로 push
REPO_LEGACY = r"""
stages: [build, deploy-dev, deploy-stage, push_src]
variables:
  RUNNER_TAG: shell-runner
  API_URL: https://api.example.com
build:
  stage: build
  script: [pnpm install, pnpm run build]
  tags: [ "${RUNNER_TAG}" ]
  only: [ "/^(preview|dev|stg|prod)-(web|was)-v([0-9]+\\.[0-9]+\\.[0-9]+)+/" ]
deploy-dev:
  stage: deploy-dev
  script:
    - scp -r .next/standalone app@10.0.0.10:/app/web/data/
    - ssh app@10.0.0.10 "cd /app/web && docker-compose up -d"
  tags: [ "${RUNNER_TAG}" ]
  only: [ "/^dev-(web|was)-v([0-9]+\\.[0-9]+\\.[0-9]+)+/" ]
deploy-stage:
  stage: deploy-stage
  script: [ "rsync -a build/ app@10.0.0.11:/app/web/" ]
  tags: [ "${RUNNER_TAG}" ]
  when: manual
  only: [ "/^stg-(web|was)-v([0-9]+\\.[0-9]+\\.[0-9]+)+/" ]
push_src:
  stage: push_src
  script: [ "git push https://center.example.com/shop/shop.git HEAD --tags" ]
  tags: [ "${RUNNER_TAG}" ]
  only: [ "/^(preview|prod)-(web|was)-v([0-9]+\\.[0-9]+\\.[0-9]+)+/" ]
"""

# center: 이미지 빌드(전 env) + prod 수동 배포(rules·extends·!reference 섞음)
CENTER = r"""
variables:
  REGISTRY: registry.example.com
.deploy:
  image: docker:27
  tags: [docker-runner]
  script:
    - ssh app@10.0.0.20 "sed -i s/^TAG_INFO=.*/TAG_INFO=$CI_COMMIT_TAG/ .env && docker compose pull && docker compose up -d"
build-image:
  stage: build
  tags: [builder]
  script:
    - docker build -t $REGISTRY/shop/web:$CI_COMMIT_TAG .
    - docker push $REGISTRY/shop/web:$CI_COMMIT_TAG
  rules:
    - if: '$CI_COMMIT_TAG =~ /^(preview|dev|stg|prod)-(web|was)-v\d+\.\d+\.\d+$/'
deploy-prod:
  extends: .deploy
  before_script: !reference [.deploy, script]
  rules:
    - if: '$CI_COMMIT_TAG =~ /^prod-(web|was)-v\d+\.\d+\.\d+$/'
      when: manual
"""

DOCKER_LEGACY = """\
FROM registry.example.com/infra/nodejs:v18
ENV LOGS='/app/logs'
COPY node-startup.sh /bin/node-startup.sh
ADD src/ /app/
"""

DOCKER_NEW = """\
ARG NODE=20
FROM node:${NODE}-slim AS deps
RUN pnpm install
FROM deps AS runner
CMD ["node", "dist/main.js"]
"""

COMPOSE_DIRECT = """\
services:
  web:
    image: registry.example.com/infra/nodejs:v18
    volumes:
      - ${PWD}/data:/app
      - ${PWD}/node-startup.sh:/bin/node-startup.sh
"""

COMPOSE_IMAGE = """\
services:
  web:
    image: ${REGISTRY_URL}/shop/web:${TAG_INFO}
  db:
    image: mysql:8.4
"""


def test_repo_ci_direct_vs_push_per_env():
    r = analyze_ci(REPO_LEGACY, "web", {"shell-runner": "shell"})
    assert r["envs"]["dev"]["direct"] is False          # 자동 직배포
    assert r["envs"]["stg"]["direct"] is True           # 수동 직배포
    assert "push" in r["envs"]["prod"] and "push" in r["envs"]["preview"]
    assert "direct" not in r["envs"]["prod"]
    assert r["executor"] == {"value": "shell", "guess": False}  # ${RUNNER_TAG} 펼쳐서 표에서 찾음
    assert r["tags"] == ["shell-runner"]


def test_center_ci_rules_extends_and_custom_tags():
    r = analyze_ci(CENTER, "web", {"builder": "shell"})
    assert r is not None  # !reference 태그에서 터지지 않음
    assert r["envs"]["dev"] == {"build_image": False}
    assert r["envs"]["prod"]["deploy_image"] is True    # rules 의 when: manual
    assert "deploy_image" not in r["envs"].get("stg", {})  # deploy-prod 는 prod 만
    assert r["executor"]["value"] == "shell"            # 표에 있는 태그(builder)가 우선


def test_executor_guess_when_tag_unknown():
    r = analyze_ci(CENTER, "web", {})
    assert r["executor"]["guess"] is True and r["executor"]["value"] == "docker"  # image: 있음 → docker 추정
    assert analyze_ci("build:\n  script: [make]\n", "web", {})["executor"] is None


def test_unreadable_ci_is_none():
    assert analyze_ci(None) is None
    assert analyze_ci("build: [unclosed") is None
    assert analyze_ci("- just\n- a list\n") is None


def test_split_image_and_runtime():
    assert split_image("registry.example.com:5000/infra/nodejs:v18") == ("infra/nodejs", "v18")
    assert split_image("node:20-slim@sha256:abc") == ("node", "20-slim")
    assert split_image("${REGISTRY_URL}/shop/web:${TAG}") == ("shop/web", "${TAG}")
    assert detect_runtime("infra/nodejs", "v18") == ("node", "18")
    assert detect_runtime("infra/nodejs", "0.0.3") == ("node", None)       # 사내 태그 → 버전 모름
    assert detect_runtime("infra/springboot", "0.1.3-java17") == ("java", "17")
    assert detect_runtime("eclipse-temurin", "17-jre") == ("java", "17")
    assert detect_runtime("infra/nginx", "1.27.4") == ("nginx", "1.27.4")
    assert detect_runtime("busybox", "1.36") == (None, None)


def test_dockerfile_legacy_and_multistage():
    old = analyze_dockerfile(DOCKER_LEGACY)
    assert old["image"] == "infra/nodejs" and old["runtime_version"] == "18"
    assert old["copies_startup"] is True and old["has_cmd"] is False
    new = analyze_dockerfile(DOCKER_NEW)
    assert (new["image"], new["tag"]) == ("node", "20-slim")  # ARG 기본값 + FROM 별칭 추적
    assert new["runtime"] == "node" and new["runtime_version"] == "20"
    assert new["copies_startup"] is False and new["has_cmd"] is True
    assert analyze_dockerfile("# no from\nRUN true\n") is None


def test_compose_image_vs_direct():
    d = analyze_compose(COMPOSE_DIRECT)
    assert d["path"] == "direct" and d["startup"] is True
    i = analyze_compose(COMPOSE_IMAGE)
    assert i["path"] == "image" and i["startup"] is False
    assert analyze_compose("version: '3'\n") is None


def test_build_row_combines_everything():
    row = build_row(
        {"name": "shop web", "group": "shop", "type": "web"},
        {
            "repo_ci": REPO_LEGACY,
            "center_ci": CENTER,
            "dockerfile": DOCKER_LEGACY,
            "startup": None,  # config 에 start.sh 파일은 없지만 Dockerfile 이 COPY → 있음
            "compose": {"dev": COMPOSE_DIRECT, "prod": COMPOSE_DIRECT},
        },
        {"shell-runner": "shell", "builder": "shell"},
    )
    d = row["data"]
    assert row["service"] == "shop web" and row["group"] == "shop"
    assert (d["runtime"], d["runtime_version"], d["base_image"], d["base_tag"]) == ("node", "18", "infra/nodejs", "v18")
    assert d["deploy"]["dev"] == {"path": "direct", "manual": False, "mismatch": False}
    assert d["deploy"]["stg"] == {"path": "direct", "manual": True, "mismatch": False}
    assert d["deploy"]["prod"] == {"path": "image", "manual": True, "mismatch": True}  # compose 는 직배포 모양 → ⚠
    assert d["deploy"]["preview"]["path"] == "image" and d["deploy"]["preview"]["manual"] is None  # center 배포 job 없음
    assert "lab" not in d["deploy"]
    assert d["executor_repo"]["value"] == "shell" and d["executor_center"]["value"] == "shell"
    assert d["startup"] is True
    assert d["env_keys"] == 3 and len(row["env_hash"]) == 64
    assert "https://api.example.com" not in str(row)  # env 값은 해시에만


def test_build_row_env_hash_changes_with_values_only():
    a = build_row({"name": "x"}, {"repo_ci": REPO_LEGACY})
    b = build_row({"name": "x"}, {"repo_ci": REPO_LEGACY.replace("api.example.com", "api2.example.com")})
    assert a["data"]["env_keys"] == b["data"]["env_keys"] and a["env_hash"] != b["env_hash"]


def test_build_row_repo_build_only_and_compose_fallback():
    repo_build_only = r"""
build:
  script: [./gradlew build]
  only: [ "/^dev-was-v.*/" ]
"""
    row = build_row(
        {"name": "api", "type": "was"},
        {"repo_ci": repo_build_only, "compose": {"prod": COMPOSE_IMAGE}},
    )
    dep = row["data"]["deploy"]
    assert dep["dev"]["path"] == "build"                     # 빌드만 하고 끝
    assert dep["prod"] == {"path": "image", "manual": None, "mismatch": False}  # CI 엔 없음 → compose 로
    assert row["data"]["startup"] is False                   # compose 를 봤는데 start.sh 마운트 없음


def test_build_row_nothing_known():
    row = build_row({"name": "ghost"}, {})
    d = row["data"]
    assert d["deploy"] == {} and d["startup"] is None and d["env_keys"] is None and row["env_hash"] is None


def test_parse_targets():
    runners, services = parse_targets(
        "runners: {a: shell}\nservices:\n  - {name: one, type: web}\n  - {type: was}\n  - nope\n"
    )
    assert runners == {"a": "shell"} and [s["name"] for s in services] == ["one"]


def test_cmd_shape_reads_local_files_and_uploads(monkeypatch, tmp_path, capsys):
    import types

    import runner.cli as cli

    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "repo.yml").write_text(REPO_LEGACY)
    (tmp_path / "ci" / "web.Dockerfile").write_text(DOCKER_NEW)
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "runners: {shell-runner: shell}\n"
        "services:\n"
        "  - name: shop web\n"
        "    repo_ci: {file: ci/repo.yml}\n"
        "    dockerfile: {file: ci/web.Dockerfile}\n"
        "    startup: {file: ci/missing-start.sh}\n"            # 없음 = start.sh 없음(오류 아님)
        "    center_ci: {gitlab: center, project: shop/shop, path: .gitlab-ci.yml}\n"  # center 미설정 → 건너뜀
        "    compose: {prod: {file: ci/nope.yml}}\n"            # 못 읽음 → 안내
    )
    sent = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_shapes(self, shapes, replace=False):
            sent.update(shapes=shapes, replace=replace)
            return {"accepted": len(shapes), "removed": 0}

        def close(self):
            pass

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="main", connect_timeout=1,
    )
    cli.cmd_shape(cfg)
    assert sent["replace"] is True
    d = sent["shapes"][0]["data"]
    assert d["runtime_version"] == "20" and d["startup"] is False
    assert d["executor_repo"]["value"] == "shell" and d["executor_center"] is None
    out = capsys.readouterr().out
    assert "1개 서비스" in out and "shop web:compose.prod" in out and "startup" not in out
