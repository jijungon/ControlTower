"""비교표 판독기(cishape) — 실제 파일 모양을 본뜬 가짜 CI/Dockerfile/compose 로 검증."""
from runner.cishape import (
    analyze_ci,
    analyze_compose,
    analyze_config_dir,
    analyze_dockerfile,
    build_row,
    code_versions,
    config_dirs,
    deploy_targets,
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
    assert (r["executor"]["value"], r["executor"]["guess"], r["executor"]["tags"]) == ("shell", False, ["shell-runner"])  # ${RUNNER_TAG} 펼쳐서 표에서 찾음
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
    # 태그를 모름 → job 마다 image: 로 짐작: build(이미지 없음)=shell, deploy-prod(image: docker)=docker → 섞임
    assert r["executor"]["guess"] is True and r["executor"]["counts"] == {"shell": 1, "docker": 1}
    assert r["executor"]["tags"] == ["builder", "docker-runner"]  # 화면에 '어느 태그 때문에 추정인지' 보여줄 용도
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
    assert d["path"] == "direct" and d["startup"] is True and d["start"] == "mount"  # start.sh 형태 = shell
    i = analyze_compose(COMPOSE_IMAGE)
    assert i["path"] == "image" and i["startup"] is False and i["start"] == "image"  # 이미지 CMD 사용


def test_compose_moved_to_command():
    moved = """\
services:
  web:
    image: node:22-slim
    volumes: ["${PWD}/data:/app"]
    command: ["sh", "-c", "umask 026 && exec node standalone/server.js >> /app/logs/server.log 2>&1"]
"""
    c = analyze_compose(moved)
    assert c["start"] == "command" and c["path"] == "direct"  # 직배포(볼륨) 이지만 start.sh 없이 command 로 실행
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
    assert d["deploy"]["dev"] == {"path": "direct", "by": "repo", "manual": False, "mismatch": False}
    assert d["deploy"]["stg"] == {"path": "direct", "by": "repo", "manual": True, "mismatch": False}
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
    assert dep["prod"] == {"path": "image", "by": "compose", "manual": None, "mismatch": False}  # CI 엔 없음 → compose 로 짐작
    assert row["data"]["startup"] is False                   # compose 를 봤는데 start.sh 마운트 없음


def test_build_row_nothing_known():
    row = build_row({"name": "ghost"}, {})
    d = row["data"]
    assert d["deploy"] == {} and d["startup"] is None and d["env_keys"] is None and row["env_hash"] is None


def test_parse_targets():
    runners, services, config = parse_targets(
        "runners: {a: shell}\nservices:\n  - {name: one, type: web}\n  - {type: was}\n  - nope\nconfig: {file: cfg}\n"
    )
    assert runners == {"a": "shell"} and [s["name"] for s in services] == ["one"] and config == {"file": "cfg"}
    assert parse_targets("services: []\n")[2] is None


def test_config_dirs_depth_three_and_flat_dockerfile():
    got = config_dirs([
        "README.md", "shop/web/Dockerfile", "shop/web/node-startup.sh", "shop/web/build/x.js", "shop/was/.gitkeep",
        ".ci/a/b", "bot/Dockerfile", "shop/README.md",
    ])
    # bot 은 타입 폴더 없이 Dockerfile 을 바로 둠 → 한 행. shop/README.md 는 Dockerfile 이 없어 행 아님
    assert got == {"shop/web": ["Dockerfile", "node-startup.sh"], "shop/was": [".gitkeep"], "bot": ["Dockerfile"]}


def test_config_dir_states():
    legacy = analyze_config_dir(["Dockerfile", "node-startup.sh"], DOCKER_LEGACY)
    assert (legacy["start"], legacy["state"], legacy["runtime_version"]) == ("start.sh", "legacy", "18")
    leftover = analyze_config_dir(["Dockerfile", "node-startup.sh"], DOCKER_NEW)  # CMD 있는데 .sh 남음
    assert (leftover["start"], leftover["state"], leftover["start_files"]) == ("dockerfile", "leftover", ["node-startup.sh"])
    done = analyze_config_dir(["Dockerfile"], DOCKER_NEW)
    assert (done["start"], done["state"]) == ("dockerfile", "done")
    java = analyze_config_dir(["Dockerfile"], "FROM reg.example.com/infra/springboot:0.1.3-java17\nCOPY app.jar /app/\n")
    assert (java["start"], java["state"], java["runtime"]) == ("base", "base", "java")
    # start.sh 가 폴더엔 있지만 Dockerfile 이 넣지도(COPY) CMD 도 없음 → 이미지 혼자 못 띄움, 서버 compose 가 줘야 함
    server = analyze_config_dir(["Dockerfile", "node-startup.sh"], "FROM reg.example.com/infra/nodejs:v18\nADD src/ /app/\n")
    assert (server["start"], server["state"]) == ("server", "server")
    nothing = analyze_config_dir([".gitkeep"], None)
    assert (nothing["start"], nothing["state"], nothing["base_image"]) == (None, "none", None)


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

        def upload_config(self, items, replace=False):
            sent.update(config=items)
            return {"accepted": len(items), "removed": 0}

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


def test_cmd_shape_scans_config_dir_and_links_services(monkeypatch, tmp_path, capsys):
    import types

    import runner.cli as cli

    cfgdir = tmp_path / "config"
    (cfgdir / "shop" / "web").mkdir(parents=True)
    (cfgdir / "shop" / "web" / "Dockerfile").write_text(DOCKER_NEW)
    (cfgdir / "shop" / "web" / "node-startup.sh").write_text("node server.js\n")  # 잔재
    (cfgdir / "shop" / "web" / "build").mkdir()  # 깊이 3 폴더는 무시
    (cfgdir / "shop" / "old").mkdir()
    (cfgdir / "shop" / "old" / "Dockerfile").write_text(DOCKER_LEGACY)
    (tmp_path / "dev-compose.yml").write_text(COMPOSE_DIRECT)
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / ".gitlab-ci.yml").write_text(REPO_LEGACY)
    (tmp_path / "repo" / ".nvmrc").write_text("22\n")  # 코드는 22, 이미지는 node:20 → 화면에서 ⚠
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "config:\n"
        "  file: config\n"
        "  merged: {shop/old: shop/web}\n"   # shop/old 는 shop/web 으로 합쳐져 안 씀
        "  compose:\n"
        "    shop/old: {dev: {file: dev-compose.yml}}\n"
        "services:\n"
        "  - name: shop web\n"
        "    config_dir: shop/web\n"   # dockerfile·startup 을 config 폴더에서
        "    repo_ci: {file: repo/.gitlab-ci.yml}\n"
    )
    sent = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_shapes(self, shapes, replace=False):
            sent["shapes"] = shapes
            return {"accepted": len(shapes), "removed": 0}

        def upload_config(self, items, replace=False):
            sent.update(config=items, replace=replace)
            return {"accepted": len(items), "removed": 0}

        def close(self):
            pass

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="main", connect_timeout=1,
    )
    cli.cmd_shape(cfg)
    items = {i["path"]: i["data"] for i in sent["config"]}
    assert set(items) == {"shop/web", "shop/old"} and sent["replace"] is True
    assert items["shop/web"]["state"] == "leftover" and items["shop/web"]["compose"] == {}
    assert items["shop/web"]["code"] == {"node": "22", "node_from": ".nvmrc", "node_rule": "exact"}
    assert items["shop/old"]["merged_into"] == "shop/web" and "merged_into" not in items["shop/web"]
    assert items["shop/old"]["code"] is None  # 연결된 서비스(repo)가 없음
    assert items["shop/old"]["state"] == "legacy" and items["shop/old"]["compose"] == {"dev": "mount"}  # start.sh 형태 = shell
    web = sent["shapes"][0]["data"]
    assert web["runtime_version"] == "20" and web["startup"] is True  # config_dir 로 채움
    assert web["start_state"] == "leftover"  # CMD 로 실행하는데 start.sh 파일만 남음
    assert "config 수집: 2개 폴더" in capsys.readouterr().out


# 이관 후 모양: repo 는 전 환경 push_src, center 가 dev/stg 는 파일로 복사(scp), prod 는 이미지
REPO_PUSH_ALL = r"""
push_src:
  script: [ "git push https://center.example.com/shop/shop.git HEAD --tags" ]
  only: [ "/^(dev|lab|stg|prod)-(web|was)-v\\d+\\.\\d+\\.\\d+/" ]
"""
CENTER_SOURCE = r"""
.copy: &copy
  script: [ "scp -r build/ app@10.0.0.30:/app/web-shop/data/" ]
build:
  script: [ "docker build -t r/shop:$CI_COMMIT_TAG .", "docker push r/shop:$CI_COMMIT_TAG" ]
  rules:
    - if: '$CI_COMMIT_TAG =~ /^prod-(web|was)-v\d+/'
deploy-dev:
  <<: *copy
  rules:
    - if: '$CI_COMMIT_TAG =~ /^dev-(web|was)-v\d+/'
    - if: '$CI_COMMIT_TAG =~ /^lab-web-v\d+/'
deploy-stg:
  <<: *copy
  rules:
    - if: '$CI_COMMIT_TAG =~ /^(dev|stg|prod)-(web|was)-v\d+/'
deploy-prod:
  script: [ "ssh app@10.0.0.31 'docker compose pull && docker compose up -d'" ]
  rules:
    - if: '$CI_COMMIT_TAG =~ /^prod-(web|was)-v\d+/'
      when: manual
"""


def test_center_copies_files_for_dev_stg():
    row = build_row({"name": "shop web", "type": "web"}, {"repo_ci": REPO_PUSH_ALL, "center_ci": CENTER_SOURCE, "compose": {"dev": COMPOSE_DIRECT}})
    dep = row["data"]["deploy"]
    assert dep["dev"] == {"path": "direct", "by": "center", "manual": False, "mismatch": False}  # compose 도 파일 방식 → 일치
    assert dep["lab"]["by"] == "center"  # deploy-dev 안의 따로 적힌 lab 규칙은 남는다
    assert dep["stg"]["by"] == "center" and "dev" in dep  # deploy-stg 의 넓은 규칙은 stg 로만
    assert dep["prod"] == {"path": "image", "manual": True, "mismatch": False}


def test_comment_lines_do_not_count():
    ci = r"""
deploy-dev:
  script:
    - |
      # 나중에 scp+ssh 방식으로 바꿀 예정 (메모)
      ssh app@10.0.0.40 "sed -i s/^TAG_INFO=.*/TAG_INFO=$CI_COMMIT_TAG/ .env && docker compose pull && docker compose up -d"
  rules:
    - if: '$CI_COMMIT_TAG =~ /^dev-web-v\d+/'
"""
    assert analyze_ci(ci, "web")["envs"]["dev"] == {"deploy_image": False}  # 주석의 scp 는 무시 → 이미지 배포


def test_code_versions_nvmrc_engines_pom():
    assert code_versions({".nvmrc": "v22\n", "package.json": '{"engines": {"node": ">=20"}}'}) == {
        "node": "22", "node_from": ".nvmrc", "node_rule": "exact",
    }
    assert code_versions({"package.json": '{"engines": {"node": ">=20.0.0"}, "dependencies": {"@nestjs/core": "^11.0.1"}}'}) == {
        "node": "20.0.0", "node_from": "package.json", "node_rule": "min", "nest": "11.0.1",
    }
    assert code_versions({"package.json": '{"engines": {"node": "^20"}}'})["node_rule"] == "exact"
    assert code_versions({"pom.xml": "<properties><java.version>17</java.version></properties>"}) == {"java": "17"}
    assert code_versions({".nvmrc": None, "package.json": "not json", "pom.xml": None}) == {}


def test_executor_majority_by_job():
    ci = r"""
variables:
  RUNNER_TAG: new-runner
build:
  image: node:22
  tags: ["${RUNNER_TAG}"]
  script: [make]
test:
  image: node:22
  tags: ["${RUNNER_TAG}"]
  script: [make test]
notify:
  tags: [old-shell]
  script: [./notify.sh]
"""
    r = analyze_ci(ci, "web", {"old-shell": "shell"})
    # 확인된 건 알림 job 하나(shell)뿐이지만 job 수로는 docker(짐작) 2 개가 많다
    ex = r["executor"]
    assert (ex["value"], ex["guess"], ex["counts"]) == ("docker", True, {"docker": 2, "shell": 1})
    # 화면 '섞임' 메모: 러너 태그별로 어떤 job 이 쓰나
    assert ex["groups"] == [
        {"tag": "new-runner", "value": "docker", "guess": True, "jobs": ["build", "test"]},
        {"tag": "old-shell", "value": "shell", "guess": False, "jobs": ["notify"]},
    ]
    r = analyze_ci(ci, "web", {"old-shell": "shell", "new-runner": "docker"})
    assert r["executor"]["value"] == "docker" and r["executor"]["guess"] is False


CENTER_DEPLOY = r"""
variables:
  SERVICE_INFO: shop
  DEPLOY_DEV_SERVERS: "10.0.0.1"
  DEPLOY_STG_WEB_SERVERS: "10.0.0.2"
  DEPLOY_STG_WAS_SERVERS: "10.0.0.3"
  DEPLOY_PRIVIEW_WEB_SERVERS: "10.0.0.4"
  DEPLOY_PROD_WEB_SERVERS: "10.0.0.5, 10.0.0.6"
  DEPLOY_LAB_SERVERS: ""
deploy:
  rules:
    - if: '$CI_COMMIT_TAG =~ /^dev-(web|was)-v\d+/'
    - if: '$CI_COMMIT_TAG =~ /^lab-web-v\d+/'
      variables:
        APP_DIR_OVERRIDE: /app/web-lab
  script:
    - |
      # APP_DIR="/app/old-place"
      APP_DIR="${APP_DIR_OVERRIDE:-/app/\${BUILD_INFO}-\${SERVICE_INFO}}"
"""


def test_deploy_targets_servers_and_dir():
    web = deploy_targets(CENTER_DEPLOY.replace('  DEPLOY_LAB_SERVERS: ""', '  DEPLOY_LAB_SERVERS: "10.0.0.9"'), "web")
    assert web.pop("lab") == {"hosts": ["10.0.0.9"], "dir": "/app/web-lab"}  # lab 규칙의 APP_DIR_OVERRIDE
    assert web == {
        "dev": {"hosts": ["10.0.0.1"], "dir": "/app/web-shop"},
        "stg": {"hosts": ["10.0.0.2"], "dir": "/app/web-shop"},       # 타입이 맞는 STG_WEB 우선
        "preview": {"hosts": ["10.0.0.4"], "dir": "/app/web-shop"},   # PRIVIEW 오타도 preview
        "prod": {"hosts": ["10.0.0.5", "10.0.0.6"], "dir": "/app/web-shop"},
    }                                                                  # 빈 LAB 은 없음, 주석의 old-place 는 무시
    was = deploy_targets(CENTER_DEPLOY, "was")
    assert was["stg"]["hosts"] == ["10.0.0.3"] and "prod" not in was and was["dev"]["dir"] == "/app/was-shop"
    assert deploy_targets("deploy:\n  script: [echo]\n") == {}


def test_cmd_shape_ssh_plan_and_read(monkeypatch, tmp_path, capsys):
    import types

    import runner.cli as cli

    (tmp_path / "config" / "shop" / "web").mkdir(parents=True)
    (tmp_path / "config" / "shop" / "web" / "Dockerfile").write_text(DOCKER_NEW)
    (tmp_path / "center.yml").write_text(CENTER_DEPLOY)
    (tmp_path / "dev-compose.yml").write_text(COMPOSE_DIRECT)
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "gateways: {prod: gw-prod}\n"        # prod 서버는 직접 등록 안 됨 → gw 를 거쳐 읽음
        "gateway_user: app\n"
        "config: {file: config}\n"
        "services:\n"
        "  - name: shop web\n"
        "    type: web\n"
        "    config_dir: shop/web\n"
        "    center_ci: {file: center.yml}\n"
        "    compose: {dev: {file: dev-compose.yml}}\n"   # dev 는 대상 파일에 적혀 있음 → 자동 찾기에서 제외
    )
    sent: dict = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def list_servers(self):  # 인벤토리: stg 서버만 ~/.ssh/config 에 있음
            return [{"hostname": "shop-stg", "ip": "10.0.0.2"}]

        def upload_shapes(self, shapes, replace=False):
            return {"accepted": len(shapes), "removed": 0}

        def upload_config(self, items, replace=False):
            sent["config"] = {i["path"]: i["data"] for i in items}
            return {"accepted": len(items), "removed": 0}

        def close(self):
            pass

    reads = []

    def fake_read(alias, path, timeout=8):
        reads.append((alias, path))
        return COMPOSE_IMAGE, None

    def fake_read_via(gw, target, path, timeout=8, user=None):
        reads.append((f"{gw}->{user}@{target}", path))
        return COMPOSE_DIRECT, None

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    monkeypatch.setattr(cli, "read_file", fake_read)
    monkeypatch.setattr(cli, "read_file_via", fake_read_via)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="main", connect_timeout=1,
    )
    # 1) 계획만: 접속 안 함
    cli.cmd_shape(cfg, ssh_mode="plan")
    out = capsys.readouterr().out
    assert reads == []
    # stg·preview·prod (dev 는 이미 적힘): stg 직접 · prod gw 경유 · preview 길 없음
    assert "서버 compose 자동 찾기: 3곳 (직접 1 · gw 경유 1 · 길 없음 1)" in out
    assert "shop-stg:/app/web-shop/docker-compose.yml" in out and "gw-prod → 10.0.0.5:/app/web-shop/docker-compose.yml" in out
    assert "접속 안 함" in out
    assert sent["config"]["shop/web"]["compose_src"] == {"dev": {"kind": "file", "note": None, "where": "dev-compose.yml"}}
    # 계획만: 위치를 찾은 환경은 '안 읽음' 이 아니라 'planned'
    assert {e: m["state"] for e, m in sent["config"]["shop/web"]["compose_miss"].items()} == {"stg": "planned", "preview": "planned", "prod": "planned"}
    assert "gw-prod → 10.0.0.5" in sent["config"]["shop/web"]["compose_miss"]["prod"]["reason"]
    # 2) 실제로 읽기: 인벤토리에 있는 stg 만 SSH
    cli.cmd_shape(cfg, ssh_mode="read")
    assert reads == [
        ("shop-stg", "/app/web-shop/docker-compose.yml"),
        ("gw-prod->app@10.0.0.5", "/app/web-shop/docker-compose.yml"),  # gw 위에서 안쪽 서버로
    ]
    data = sent["config"]["shop/web"]
    assert data["compose"] == {"dev": "mount", "stg": "image", "prod": "mount"}
    assert data["compose_src"]["prod"] == {
        "kind": "ssh", "auto": True, "via": "gw-prod", "where": "gw-prod → 10.0.0.5:/app/web-shop/docker-compose.yml",
    }
    assert data["compose_src"]["stg"] == {"kind": "ssh", "auto": True, "where": "shop-stg:/app/web-shop/docker-compose.yml"}
    # 실제로 읽기: 직접 등록도 gw 도 없는 preview 만 '못 읽음' + 이유
    assert {e: m["state"] for e, m in data["compose_miss"].items()} == {"preview": "fail"}
    assert "직접 등록 안 된" in data["compose_miss"]["preview"]["reason"] and "gateways:" in data["compose_miss"]["preview"]["reason"]


def test_src_info_note_per_file_overrides_service_note():
    from runner.cli import _src_info

    assert _src_info({"file": "a.yml"}, note="옛 사본") == {"kind": "file", "note": "옛 사본", "where": "a.yml"}
    assert _src_info({"file": "a.yml", "note": ""}, note="옛 사본")["note"] is None  # 이 파일은 실제 사본
    assert _src_info({"ssh": "h", "path": "/app/x.yml"}, auto=True) == {"kind": "ssh", "auto": True, "where": "h:/app/x.yml"}


def test_read_file_via_builds_nested_ssh(monkeypatch):
    import subprocess

    import runner.conn as conn

    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="services: {}\n", stderr="")

    monkeypatch.setattr(conn.subprocess, "run", fake_run)
    text, err = conn.read_file_via("gw-prod", "10.0.0.5", "/app/web shop/docker-compose.yml", 5, user="app")
    assert (text, err) == ("services: {}\n", None)
    argv = seen["argv"]
    assert argv[0] == "ssh" and "gw-prod" in argv  # 바깥: PC → gw
    inner = argv[-1]  # 안쪽: gw 위에서 실행할 명령(따옴표 처리됨)
    assert inner.startswith("ssh -o BatchMode=yes -o ConnectTimeout=5 app@10.0.0.5 cat -- ")
    assert "'/app/web shop/docker-compose.yml'" in inner
