"""비교표 판독기(cishape) — 실제 파일 모양을 본뜬 가짜 CI/Dockerfile/compose 로 검증."""
from runner.cishape import (
    analyze_ci,
    analyze_compose,
    analyze_config_dir,
    analyze_dockerfile,
    build_row,
    build_runtimes,
    code_versions,
    config_dirs,
    confirm_executor,
    deploy_targets,
    detect_runtime,
    parse_build_log_versions,
    parse_executor_log,
    parse_targets,
    parse_version_tag,
    pick_versions,
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
    assert runners == {"a": "shell"} and [s["name"] for s in services] == ["one"] and config == [{"file": "cfg"}]
    assert parse_targets("services: []\n")[2] == []
    # config repo 여러 개(목록) — 서비스 묶음마다 config repo 가 따로일 때
    assert parse_targets("config:\n  - {project: a/config}\n  - {project: b/config, group: b}\n  - nope\n")[2] == [
        {"project": "a/config"}, {"project": "b/config", "group": "b"},
    ]


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
    (cfgdir / "shop" / "job").mkdir()
    (cfgdir / "bot").mkdir()
    (cfgdir / "bot" / "Dockerfile").write_text(DOCKER_NEW)
    (cfgdir / "shop" / "job" / "Dockerfile").write_text(DOCKER_NEW)
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
        "  - {name: shop mgr, group: shop, type: manager, config_dir: shop/job}\n"   # 폴더 하나(job)를 역할 둘이 같이 씀
        "  - {name: shop wrk, type: worker, config_dir: shop/job}\n"
        "  - {name: bot, type: bot, config_dir: bot}\n"   # 타입 폴더 없는 곳은 나누지 않음
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
    assert set(items) == {"shop/web", "shop/old", "shop/manager", "shop/worker", "bot"} and sent["replace"] is True
    assert items["shop/web"]["state"] == "leftover" and items["shop/web"]["compose"] == {}
    assert items["shop/web"]["code"] == {"node": "22", "node_from": ".nvmrc", "node_rule": "exact"}
    assert items["shop/old"]["merged_into"] == "shop/web" and "merged_into" not in items["shop/web"]
    assert items["shop/web"]["deploy_envs"] == ["dev", "preview", "prod", "stg"]  # 연결된 서비스(repo CI)가 배포하는 환경
    assert "deploy_envs" not in items["shop/old"]  # 연결된 서비스 없음 → 모름
    # 역할로 나뉜 폴더는 역할마다 한 줄 — 실제 폴더는 folder, 폴더 이름 그대로면 folder 없음
    assert items["shop/manager"]["folder"] == items["shop/worker"]["folder"] == "shop/job"
    assert "folder" not in items["shop/web"] and "shop/job" not in items
    # 그룹: 연결된 서비스의 group, 연결 안 된 폴더는 config 에 연결된 서비스들의 가장 많은 그룹
    assert items["shop/manager"]["group"] == "shop" and items["shop/old"]["group"] == "shop"
    assert items["shop/old"]["code"] is None  # 연결된 서비스(repo)가 없음
    assert items["shop/old"]["state"] == "legacy" and items["shop/old"]["compose"] == {"dev": "mount"}  # start.sh 형태 = shell
    web = sent["shapes"][0]["data"]
    assert web["runtime_version"] == "20" and web["startup"] is True  # config_dir 로 채움
    assert web["start_state"] == "leftover"  # CMD 로 실행하는데 start.sh 파일만 남음
    assert "config 수집: 5개 줄" in capsys.readouterr().out


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
    assert code_versions({"pom.xml": "<properties><java.version>17</java.version></properties>"}) == {"java": "17", "java_from": "pom.xml"}
    # Gradle — toolchain 우선, 없으면 sourceCompatibility('VERSION_1_8' = 8), kotlin DSL 도
    gradle = "plugins { id 'org.springframework.boot' version '3.4.5' }\njava {\n  toolchain {\n    languageVersion = JavaLanguageVersion.of(17)\n  }\n}\n"
    assert code_versions({"build.gradle": gradle}) == {"java": "17", "java_from": "build.gradle"}
    assert code_versions({"build.gradle": "sourceCompatibility = JavaVersion.VERSION_1_8\n"})["java"] == "8"
    assert code_versions({"build.gradle": "sourceCompatibility = '21'\n"})["java"] == "21"
    assert code_versions({"build.gradle.kts": "java { toolchain { languageVersion.set(JavaLanguageVersion.of(21)) } }"}) == {"java": "21", "java_from": "build.gradle.kts"}
    assert code_versions({"build.gradle": "dependencies { implementation 'x:y:1.0' }"}) == {}  # 버전 줄 없음
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
    # 화면 'job 별' 칸: 러너 태그별로 어떤 job 이 쓰나 + 어떻게 정했나(why)
    assert ex["groups"] == [
        {"tag": "new-runner", "value": "docker", "guess": True, "why": "image: 있음", "jobs": ["build", "test"],
         "images": {"build": "node:22", "test": "node:22"}},  # 펼치면 job 마다 쓰는 이미지
        {"tag": "old-shell", "value": "shell", "guess": False, "why": "runners 표", "jobs": ["notify"], "images": {}},
    ]
    r = analyze_ci(ci, "web", {"old-shell": "shell", "new-runner": "docker"})
    assert r["executor"]["value"] == "docker" and r["executor"]["guess"] is False


def test_executor_job_images_default_dict_and_vars():
    ci = r"""
default:
  image: alpine:3.20
variables:
  DEPLOY_IMAGE: deploy-image:latest
.ssh:
  image: {name: "${DEPLOY_IMAGE}", entrypoint: [""]}
deploy:
  extends: .ssh
  tags: [d]
  script: [ssh x]
lint:
  tags: [d]
  script: [make lint]
"""
    g = analyze_ci(ci, "web")["executor"]["groups"][0]
    # extends 의 {name: …} 모양 + 변수 펼침, 이미지 안 적은 job 은 default 이미지
    assert g["images"] == {"deploy": "deploy-image:latest", "lint": "alpine:3.20"}


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


def test_deploy_targets_role_split_servers():
    # 같은 이미지(app)를 prod 에서만 역할별 서버(manager·syncer)에 나눠 까는 경우 — 폴더는 BUILD_INFO(app) 그대로
    ci = (
        "variables:\n"
        '  SERVICE_INFO: acct\n'
        '  DEPLOY_DEV_SERVERS: "10.0.1.1"\n'
        '  DEPLOY_PROD_MGR_SERVERS: "10.0.1.2"\n'
        '  DEPLOY_PROD_WRK_SERVERS: "10.0.1.3,10.0.1.4"\n'
        "deploy:\n"
        "  script:\n"
        '    - APP_DIR="/app/\\${BUILD_INFO}-\\${SERVICE_INFO}"\n'
    )
    mgr = deploy_targets(ci, "app", "mgr")
    assert mgr == {"dev": {"hosts": ["10.0.1.1"], "dir": "/app/app-acct"}, "prod": {"hosts": ["10.0.1.2"], "dir": "/app/app-acct"}}
    assert deploy_targets(ci, "app", "wrk")["prod"]["hosts"] == ["10.0.1.3", "10.0.1.4"]
    assert "prod" not in deploy_targets(ci, "app")  # 역할을 안 정하면 prod 는 어느 서버인지 모름
    # 표 타입(manager)과 태그 타입(app)이 다를 때: 태그 판정은 tag_type 으로
    build = "build:\n  script:\n    - docker build -t r/x:$T .\n    - docker push r/x:$T\n  rules:\n    - if: '$CI_COMMIT_TAG =~ /^(dev|prod)-app-v/'\n"
    row = build_row({"name": "acct manager", "type": "manager", "tag_type": "app"}, {"center_ci": build})
    assert row["data"]["type"] == "manager" and set(row["data"]["deploy"]) == {"dev", "prod"}
    assert build_row({"name": "acct manager", "type": "manager"}, {"center_ci": build})["data"]["deploy"] == {}  # manager 태그는 없음


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

    def fake_read_via(gw, target, path, timeout=8, user=None, sudo=False):
        reads.append((f"{gw}->{'sudo:' if sudo else ''}{user}@{target}", path))
        return COMPOSE_DIRECT, None

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    monkeypatch.setattr(cli, "read_file", fake_read)
    monkeypatch.setattr(cli, "read_file_via", fake_read_via)
    gw_lookups: list[str] = []
    gw_known: dict[str, str] = {}  # gw 로그인 계정 ssh 설정에 등록된 이름(처음엔 없음)

    def fake_gw_aliases(gw, timeout=8, sudo=False):
        gw_lookups.append(f"{gw}{'(sudo)' if sudo else ''}")
        return dict(gw_known)

    monkeypatch.setattr(cli, "gateway_aliases", fake_gw_aliases)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="main", connect_timeout=1,
    )
    # 1) 계획만: 접속 안 함
    cli.cmd_shape(cfg, ssh_mode="plan")
    out = capsys.readouterr().out
    assert reads == [] and gw_lookups == []  # 계획만: gw 설정도 안 읽음
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
    assert gw_lookups == ["gw-prod"]  # gw 설정은 gw 마다 한 번
    # 3) gw 에 이름으로 등록된 서버면 주소 대신 그 이름으로(gw 의 계정·키·지문 설정 그대로, user@ 안 붙임)
    gw_known["10.0.0.5"] = "shop-prod01"
    reads.clear()
    cli.cmd_shape(cfg, ssh_mode="read")
    assert ("gw-prod->None@shop-prod01", "/app/web-shop/docker-compose.yml") in reads
    assert sent["config"]["shop/web"]["compose_src"]["prod"]["where"] == "gw-prod → shop-prod01:/app/web-shop/docker-compose.yml"
    # 4) gateway_sudo: 서버 이름이 gw 의 root 계정에만 있으면 root 설정으로(sudo -n) 읽고, 출처에 (sudo)
    targets.write_text("gateway_sudo: [gw-prod]\n" + targets.read_text())
    reads.clear()
    gw_lookups.clear()
    cli.cmd_shape(cfg, ssh_mode="read")
    assert gw_lookups == ["gw-prod(sudo)"]
    assert ("gw-prod->sudo:None@shop-prod01", "/app/web-shop/docker-compose.yml") in reads
    assert sent["config"]["shop/web"]["compose_src"]["prod"]["where"].startswith("gw-prod(sudo) → shop-prod01:")


def test_read_source_via_gateway(monkeypatch):
    import types

    import runner.cli as cli

    calls = []
    monkeypatch.setattr(cli, "read_file_via", lambda gw, t, p, timeout=8, user=None, sudo=False: (calls.append((gw, t, p, sudo)) or ("x: 1\n", None)))
    cfg = types.SimpleNamespace(connect_timeout=3)
    assert cli._read_source({"ssh": "app-was01", "via": "gw-prod", "path": "/app/a/docker-compose.yml"}, cfg, ".") == (True, "x: 1\n")
    cli._read_source({"ssh": "app-mgr", "via": "gw-prod", "path": "/app/b.yml", "sudo": True}, cfg, ".")
    assert calls == [("gw-prod", "app-was01", "/app/a/docker-compose.yml", False), ("gw-prod", "app-mgr", "/app/b.yml", True)]


def test_parse_ssh_aliases():
    from runner.conn import parse_ssh_aliases

    text = (
        "Host *\n  ServerAliveInterval 30\n"
        "Host app-mgr mgr\n  HostName 10.0.2.1\n  User app\n"
        "# Host old\n#  HostName 10.0.2.9\n"
        "Host app-wrk01\n    hostname 10.0.2.2\n"
        "Host dup\n  HostName 10.0.2.1\n"
    )
    assert parse_ssh_aliases(text) == {"10.0.2.1": "app-mgr", "10.0.2.2": "app-wrk01"}  # 와일드카드·주석 빼고, 같은 주소면 먼저 나온 이름


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
    # sudo: gw 의 root 설정·키로 — 비밀번호를 묻지 않게 -n
    conn.read_file_via("gw-prod", "app-mgr", "/app/x/docker-compose.yml", 5, sudo=True)
    assert seen["argv"][-1].startswith("sudo -n ssh -o BatchMode=yes -o ConnectTimeout=5 app-mgr cat -- ")


def test_parse_executor_log():
    log = (
        "\x1b[0KRunning with gitlab-runner 17.2.0 (abc)\x1b[0;m\n"
        "\x1b[0K  on builder xYz, system ID: s_1\x1b[0;m\n"
        "section_start:1:prepare_executor\r\x1b[0K\x1b[0K\x1b[36;1mPreparing the \"docker+machine\" executor\x1b[0;m\n"
        "\x1b[0KUsing Docker executor with image ruby:3.1 ...\x1b[0;m\n"
    )
    assert parse_executor_log(log) == {"executor": "docker", "raw": "docker+machine", "image": "ruby:3.1"}
    assert parse_executor_log('Preparing the "shell" executor\nUsing Shell (bash) executor...') == {"executor": "shell", "raw": "shell"}
    assert parse_executor_log("no header") is None and parse_executor_log(None) is None


def test_confirm_executor_overrides_guess_and_resummarizes():
    cell = {
        "value": "docker", "guess": True, "tags": ["builder", "deploy"], "counts": {"shell": 2, "docker": 3},
        "groups": [
            {"tag": "builder", "value": "shell", "guess": True, "why": "image: 없음", "jobs": ["build", "build-manual"], "images": {}},
            {"tag": "deploy", "value": "docker", "guess": True, "why": "image: 있음", "jobs": ["d1", "d2", "d3"], "images": {"d1": "x"}},
        ],
    }
    out = confirm_executor(cell, {"builder": {"executor": "docker", "job_id": 41, "default_image": "docker:27"}})
    b = out["groups"][0]
    assert (b["value"], b["guess"], b["why"], b["default_image"]) == ("docker", False, "job 로그 #41", "docker:27")
    assert out["groups"][1]["guess"] is True  # 확인 못 한 그룹은 추정 그대로
    assert (out["value"], out["guess"]) == ("docker", False) and "counts" not in out  # 이제 전부 docker
    assert confirm_executor(cell, {}) is cell and confirm_executor(None, {"x": {}}) is None


def test_cmd_shape_reads_gitlab_by_default_local_only_when_chosen(monkeypatch, tmp_path, capsys):
    """기본은 repo:/center:/project: 를 무조건 GitLab API 로(토큰 없으면 올리지 않고 멈춤), 로컬 사본은 --source local 일 때만.
    API 로 읽은 쪽은 job 로그 맨 윗줄로 executor 를 확정한다."""
    import types

    import runner.cli as cli

    center_ci = (
        "build:\n  tags: [builder]\n  script: [docker build -t r/x .]\n"
        "  rules: [{if: '$CI_COMMIT_TAG =~ /^(dev|prod)-web-v/'}]\n"
        "deploy:\n  image: deploy-image:latest\n  tags: [deployer]\n  script: [ssh x]\n"
    )
    (tmp_path / "center.yml").write_text(center_ci.replace("builder", "local-builder"))
    (tmp_path / "config" / "shop" / "web").mkdir(parents=True)
    (tmp_path / "config" / "shop" / "web" / "Dockerfile").write_text(DOCKER_NEW)
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "config: {file: config, project: shop/config}\n"
        "services:\n"
        "  - name: shop web\n"
        "    type: web\n"
        "    center: shop/shop\n"                      # 기본: 이 프로젝트를 GitLab API 로
        "    center_ci: {file: center.yml}\n"         # --source local 일 때만 읽는 로컬 사본
        "    config_dir: shop/web\n"
    )
    sent: dict = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_shapes(self, shapes, replace=False):
            sent["shapes"] = {s["service"]: s["data"] for s in shapes}
            return {"accepted": len(shapes), "removed": 0}

        def upload_config(self, items, replace=False):
            sent["config"] = {i["path"]: i["data"] for i in items}
            return {"accepted": len(items), "removed": 0}

        def close(self):
            pass

    calls: list[str] = []
    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    monkeypatch.setattr(cli, "fetch_repo_file", lambda u, t, p, path, ref="main", timeout=8: calls.append(f"file {p}:{path}") or (center_ci if path == ".gitlab-ci.yml" else DOCKER_NEW))
    monkeypatch.setattr(cli, "fetch_repo_tree", lambda u, t, p, ref="main", timeout=8: calls.append(f"tree {p}") or ["shop/web/Dockerfile"])
    monkeypatch.setattr(cli, "fetch_recent_jobs", lambda u, t, p, timeout=8: calls.append(f"jobs {p}") or [
        {"id": 7, "name": "deploy", "status": "success", "runner_id": 2, "runner_name": "deploy-01", "web_url": ""},
        {"id": 5, "name": "build", "status": "success", "runner_id": 1, "runner_name": "build-01", "web_url": ""},
    ])
    logs = {5: 'Preparing the "shell" executor\n', 7: 'Preparing the "docker" executor\nUsing Docker executor with image deploy-image:latest ...\n'}
    monkeypatch.setattr(cli, "fetch_job_log_head", lambda u, t, p, jid, timeout=8: calls.append(f"log {jid}") or logs[jid])

    def cfg(token: str):
        return types.SimpleNamespace(
            shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
            gitlab_center_url="http://center" if token else "", gitlab_center_token=token, gitlab_ref="main", connect_timeout=1,
        )

    # 1) 토큰 없음 → GitLab 을 못 읽으니 멈춤(빈 표를 올리지 않음), API·로컬 둘 다 안 읽음
    cli.cmd_shape(cfg(""))
    out = capsys.readouterr().out
    assert calls == [] and sent == {} and "GitLab 토큰이 없어 멈춤(center)" in out and "--source local" in out
    # 2) --source local 을 고르면 로컬 사본 — executor 는 추정
    cli.cmd_shape(cfg(""), source="local")
    assert calls == [] and "center 로컬 사본 · config 로컬 사본 (--source local)" in capsys.readouterr().out
    ex = sent["shapes"]["shop web"]["executor_center"]
    assert {g["tag"]: g["guess"] for g in ex["groups"]} == {"local-builder": True, "deployer": True}
    # 3) 토큰 있음(기본) → API 로, job 로그로 확정(같은 러너는 한 번만)
    cli.cmd_shape(cfg("tok"))
    out = capsys.readouterr().out
    assert "center GitLab API · config GitLab API" in out
    assert "file shop/shop:.gitlab-ci.yml" in calls and "tree shop/config" in calls
    assert calls.count("jobs shop/shop") == 1 and sorted(c for c in calls if c.startswith("log")) == ["log 5", "log 7"]
    ex = sent["shapes"]["shop web"]["executor_center"]
    groups = {g["tag"]: g for g in ex["groups"]}
    assert (groups["builder"]["value"], groups["builder"]["guess"], groups["builder"]["why"]) == ("shell", False, "job 로그 #5")
    assert (groups["deployer"]["value"], groups["deployer"]["why"]) == ("docker", "job 로그 #7")
    assert (groups["builder"]["runner_name"], groups["deployer"]["runner_name"]) == ("build-01", "deploy-01")  # GitLab 에 등록된 러너 이름
    assert "default_image" not in groups["deployer"]  # deploy 는 image: 를 적어 둠 → 러너 기본 이미지 아님
    assert "shop/web" in sent["config"]
    # 4) --source local 이면 토큰이 있어도 로컬
    calls.clear()
    cli.cmd_shape(cfg("tok"), source="local")
    assert calls == []


def test_pick_gitlab_or_local_copy():
    from runner.cli import _pick

    both = {"gitlab": "center", "project": "g/config", "path": "web/Dockerfile", "file": "~/c/web/Dockerfile", "note": "x"}
    assert _pick(both, "api") == {"gitlab": "center", "project": "g/config", "path": "web/Dockerfile", "note": "x"}
    assert _pick(both, "local") == {"file": "~/c/web/Dockerfile", "note": "x"}
    assert _pick({"file": "a"}, "api") == {"file": "a"} and _pick(None, "api") is None  # 하나만 적은 건 그대로


def test_cmd_shape_reads_several_config_repos(monkeypatch, tmp_path, capsys):
    """config repo 가 서비스 묶음마다 따로면 config: 를 목록으로 — 폴더를 한 표로 모으고, 폴더마다 자기 repo 에서 Dockerfile 을 읽고,
    연결 안 된 폴더는 그 repo 의 group."""
    import types

    import runner.cli as cli

    for repo, svc, df in (("cfg-a", "shop", DOCKER_NEW), ("cfg-b", "vault", DOCKER_LEGACY)):
        (tmp_path / repo / svc / "web").mkdir(parents=True)
        (tmp_path / repo / svc / "web" / "Dockerfile").write_text(df)
    (tmp_path / "cfg-b" / "docs" / "deploy").mkdir(parents=True)  # 문서 폴더(Dockerfile 없음) → 건너뜀
    (tmp_path / "cfg-b" / "docs" / "deploy" / "FLOW.md").write_text("# flow\n")
    (tmp_path / "cfg-b" / "shop" / "web").mkdir(parents=True)  # 다른 repo 에 같은 폴더 이름 → 먼저 적은 쪽
    (tmp_path / "cfg-b" / "shop" / "web" / "Dockerfile").write_text(DOCKER_LEGACY)
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "config:\n"
        "  - {file: cfg-a, group: mall}\n"
        "  - {file: cfg-b, group: vault}\n"
    )
    sent: dict = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_config(self, items, replace=False):
            sent.update({i["path"]: i["data"] for i in items})
            return {"accepted": len(items), "removed": 0}

        def close(self):
            pass

    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="", gitlab_token="",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="", connect_timeout=1,
    )
    cli.cmd_shape(cfg)
    assert set(sent) == {"shop/web", "vault/web"}
    assert (sent["shop/web"]["group"], sent["vault/web"]["group"]) == ("mall", "vault")
    assert (sent["shop/web"]["config_repo"], sent["vault/web"]["config_repo"]) == ("cfg-a", "cfg-b")  # 어느 config repo 에서
    assert sent["shop/web"]["state"] == "done" and sent["vault/web"]["state"] == "legacy"  # 각자 자기 repo 의 Dockerfile
    out = capsys.readouterr().out
    assert "config 폴더 이름이 겹침: shop/web" in out and "config 폴더 건너뜀(Dockerfile·start.sh 없음): docs/deploy" in out


def test_build_row_host_gitlab_or_github():
    assert build_row({"name": "a", "center": "g/a"}, {})["data"]["host"] == "gitlab"
    assert build_row({"name": "b", "github": "org/b"}, {})["data"]["host"] == "github"  # GitHub 에서 빌드(아직 못 읽음)
    assert build_row({"name": "c", "compose": {}}, {})["data"]["host"] is None


def test_executor_from_logs_skips_unstarted_jobs_and_caches_by_runner(monkeypatch):
    """로그 확인은 실제로 돈 job 만(대기·수동·건너뜀 제외), 같은 러너는 한 번만 읽음."""
    import types

    import runner.cli as cli

    jobs = [
        {"id": 9, "name": "build", "status": "manual", "runner_id": None},
        {"id": 8, "name": "build", "status": "success", "runner_id": 5},
        {"id": 7, "name": "lint", "status": "failed", "runner_id": 5},
    ]
    logs: list[int] = []
    monkeypatch.setattr(cli, "fetch_recent_jobs", lambda *a, **k: jobs)
    monkeypatch.setattr(cli, "fetch_job_log_head", lambda u, t, p, jid, timeout=8: logs.append(jid) or 'Preparing the "shell" executor')
    cfg = types.SimpleNamespace(gitlab_url="http://repo", gitlab_token="t", gitlab_center_url="", gitlab_center_token="", connect_timeout=1)
    cell = {"groups": [{"tag": "a", "jobs": ["build"], "images": {}}, {"tag": "b", "jobs": ["lint"], "images": {}}]}
    out = cli._executor_from_logs("repo", "g/p", cell, cfg, {})
    assert out == {"a": {"executor": "shell", "job_id": 8}, "b": {"executor": "shell", "job_id": 8}}  # 같은 러너(5) → 로그 한 번
    assert logs == [8]
    # 토큰이 없으면 아무것도 안 함
    cfg.gitlab_token = ""
    assert cli._executor_from_logs("repo", "g/p", cell, cfg, {}) == {}


def test_ci_source_ref_and_local_fallback():
    import types

    from runner.cli import _ci_source

    cfg = types.SimpleNamespace(gitlab_url="", gitlab_token="", gitlab_center_url="", gitlab_center_token="")
    svc = {"repo": {"project": "g/web", "ref": "dev"}, "repo_ci": {"file": "a.yml"}}
    assert _ci_source(svc, "repo", cfg, "api") == ({"gitlab": "repo", "project": "g/web", "path": ".gitlab-ci.yml", "ref": "dev"}, ("g/web", "dev"))
    assert _ci_source(svc, "repo", cfg, "local") == ({"file": "a.yml"}, None)
    assert _ci_source({"repo_ci": {"file": "b.yml"}}, "repo", cfg, "api") == ({"file": "b.yml"}, None)  # 프로젝트 이름 없으면 로컬


# ── 빌드·배포 버전 (tag 로 돈 job) · repo 빌드 런타임 ─────────────────────
def test_parse_version_tag():
    assert parse_version_tag("prod-was-v1.0.9") == {"env": "prod", "type": "was", "version": "v1.0.9"}
    assert parse_version_tag("stage-web-v0.1.3b") == {"env": "stg", "type": "web", "version": "v0.1.3b"}  # 글자 붙은 버전·환경 별칭
    assert parse_version_tag("preview-app-v1.2.3.4")["version"] == "v1.2.3.4"  # 네 자리
    assert parse_version_tag("main") is None and parse_version_tag("release-1") is None and parse_version_tag(None) is None


def test_pick_versions_env_from_tag_and_newest_first():
    kinds = {"build": "build_image", "deploy-dev": "deploy_image", "deploy-prod": "deploy_image", "lint": "other"}
    jobs = [  # 최신순(GitLab 이 주는 순서)
        {"id": 30, "name": "build", "ref": "prod-was-v1.0.9", "finished_at": "2026-10-13T10:52:00Z"},
        {"id": 29, "name": "deploy-prod", "ref": "preview-was-v1.0.8", "finished_at": "2026-10-12T00:00:00Z"},
        {"id": 28, "name": "lint", "ref": "prod-was-v1.0.9", "finished_at": "2026-10-12T00:00:00Z"},
        {"id": 20, "name": "deploy-prod", "ref": "prod-was-v1.0.2", "finished_at": "2026-10-01T14:23:00Z"},
        {"id": 19, "name": "build", "ref": "prod-was-v1.0.2", "finished_at": "2026-10-01T14:00:00Z"},
        {"id": 10, "name": "deploy-prod", "ref": "prod-was-v0.9.0", "finished_at": "2026-09-01T00:00:00Z"},
    ]
    v = pick_versions(jobs, kinds)
    assert v["build"] == {"prod": {"version": "v1.0.9", "tag": "prod-was-v1.0.9", "at": "2026-10-13T10:52:00Z", "job": 30}}
    assert v["deploy"]["prod"]["version"] == "v1.0.2"  # 빌드는 v1.0.9 인데 배포는 아직 v1.0.2
    assert v["deploy"]["preview"]["version"] == "v1.0.8"  # deploy-prod job 이라도 tag 가 preview 면 preview
    assert "dev" not in v["deploy"]  # lint 같은 다른 job 은 안 셈


def test_pick_versions_skips_other_services_tags_and_roles():
    kinds = {"build": "build_image", "deploy-prod-mgr": "deploy_image", "deploy-prod-worker": "deploy_image", "deploy-dev": "deploy_image"}
    jobs = [
        {"id": 9, "name": "build", "ref": "prod-web-v2.0.0"},
        {"id": 8, "name": "deploy-prod-worker", "ref": "prod-app-v1.2.5"},
        {"id": 7, "name": "deploy-prod-mgr", "ref": "prod-app-v1.2.4"},
        {"id": 6, "name": "build", "ref": "prod-app-v1.2.5"},
        {"id": 5, "name": "deploy-dev", "ref": "dev-app-v1.2.5"},
    ]
    # 같은 center 프로젝트를 web 서비스와 같이 씀 → web tag 는 남의 것 · 역할이 mgr 면 worker 배포는 남의 것
    v = pick_versions(jobs, kinds, skip_types={"web"}, other_roles={"worker"})
    assert v["build"]["prod"]["version"] == "v1.2.5"
    assert v["deploy"]["prod"]["version"] == "v1.2.4"  # 역할 이름이 붙은 내 배포 job
    assert v["deploy"]["dev"]["version"] == "v1.2.5"  # 역할 이름이 없는 배포 job(한 서버에 둘 다)은 내 것


def test_pick_versions_direct_copy_is_build_and_deploy():
    v = pick_versions([{"id": 3, "name": "deploy-dev", "ref": "dev-web-v1.0.0"}], {"deploy-dev": "direct"})
    assert v["build"]["dev"]["version"] == v["deploy"]["dev"]["version"] == "v1.0.0"  # 파일 복사 = 빌드·배포가 한 job


def test_analyze_ci_jobs_and_build_runtimes():
    ci_text = """
variables:
  NODE_VERSION: "20"
build:
  image: node:${NODE_VERSION}-slim
  script: [npm ci, npm run build]
test:
  image: node:${NODE_VERSION}-slim
  script: [npm test]
push_src:
  image: alpine:latest
  script: [git push origin HEAD:main]
deploy:
  image: deploy-image:latest
  script: [ssh x "docker compose pull && docker compose up -d"]
"""
    ci = analyze_ci(ci_text)
    assert ci["jobs"]["build"] == {"kind": "other", "image": "node:20-slim"}  # 변수는 풀어서
    assert ci["jobs"]["push_src"]["kind"] == "push" and ci["jobs"]["deploy"]["kind"] == "deploy_image"
    # 런타임 이미지만(alpine 같은 도구 이미지 · 배포 job 은 빼고), 같은 버전끼리 묶음
    assert build_runtimes(ci) == [{"runtime": "node", "version": "20", "image": "node:20-slim", "jobs": ["build", "test"]}]
    assert build_runtimes(None) == []


def test_build_row_repo_part():
    ci = "build:\n  image: node:22\n  script: [npm run build]\n"
    row = build_row({"name": "shop web", "repo": {"project": "g/shop", "ref": "dev"}}, {"repo_ci": ci})
    assert row["data"]["repo"] == {
        "project": "g/shop", "read": True, "build": [{"runtime": "node", "version": "22", "image": "node:22", "jobs": ["build"]}],
    }
    # 프로젝트는 적었는데 CI 를 못 읽음 → read False(화면에서 '못 읽음')
    assert build_row({"name": "a", "repo": "g/a"}, {"repo_ci": None})["data"]["repo"] == {"project": "g/a", "read": False, "build": []}
    assert build_row({"name": "b", "center": "g/b"}, {})["data"]["repo"] is None  # repo 를 안 씀


def test_cmd_shape_attaches_versions_and_repo_code(monkeypatch, tmp_path, capsys):
    """API 로 읽으면 서비스마다 환경별 빌드·배포 버전(tag 로 돈 job) + repo 의 빌드 런타임·코드에 적힌 버전을 붙인다.
    web·was 가 center 프로젝트 하나를 같이 쓰면 tag 타입으로 나눈다. 같은 프로젝트의 job 목록은 한 번만 읽는다."""
    import types

    import runner.cli as cli

    center_ci = (
        "build:\n  tags: [builder]\n  script: [docker build -t r/x:$TAG .,docker push r/x:$TAG]\n"
        "  rules: [{if: '$CI_COMMIT_TAG =~ /^(dev|prod)-(web|was)-v/'}]\n"
        "deploy-prod:\n  image: deploy-image:latest\n  tags: [deployer]\n"
        "  script: [ssh x \"docker compose pull && docker compose up -d\"]\n"
        "  rules: [{if: '$CI_COMMIT_TAG =~ /^prod-(web|was)-v/', when: manual}]\n"
    )
    repo_ci = "variables: {NODE_VERSION: '20'}\nbuild:\n  image: node:${NODE_VERSION}-slim\n  tags: [repo-runner]\n  script: [npm run build]\n"
    repo_files = {".gitlab-ci.yml": repo_ci, ".nvmrc": "22\n", "package.json": '{"dependencies": {"@nestjs/core": "^10.3.0"}}'}
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "services:\n"
        "  - {name: shop web, type: web, repo: g/shop-web, center: g/shop}\n"
        "  - {name: shop was, type: was, repo: g/shop-was, center: g/shop}\n"
    )
    sent: dict = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_shapes(self, shapes, replace=False):
            sent["shapes"] = {s["service"]: s["data"] for s in shapes}
            return {"accepted": len(shapes), "removed": 0}

        def close(self):
            pass

    tag_calls: list[str] = []
    tag_jobs = [  # 최신순
        {"id": 40, "name": "build", "ref": "prod-was-v1.0.9", "finished_at": "2026-10-13T10:52:00Z"},
        {"id": 39, "name": "deploy-prod", "ref": "prod-web-v2.1.0", "finished_at": "2026-10-12T00:00:00Z"},
        {"id": 38, "name": "build", "ref": "prod-web-v2.1.0", "finished_at": "2026-10-12T00:00:00Z"},
        {"id": 30, "name": "deploy-prod", "ref": "prod-was-v1.0.2", "finished_at": "2026-10-01T00:00:00Z"},
        {"id": 29, "name": "build", "ref": "dev-was-v1.0.9", "finished_at": "2026-10-01T00:00:00Z"},
    ]
    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    monkeypatch.setattr(cli, "fetch_repo_file", lambda u, t, p, path, ref="", timeout=8: center_ci if p == "g/shop" else repo_files.get(path))
    monkeypatch.setattr(cli, "fetch_recent_jobs", lambda *a, **k: [])
    monkeypatch.setattr(cli, "fetch_tag_jobs", lambda u, t, p, timeout=8: tag_calls.append(p) or tag_jobs)
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="http://repo", gitlab_token="tok",
        gitlab_center_url="http://center", gitlab_center_token="tok", gitlab_ref="", connect_timeout=1,
    )
    cli.cmd_shape(cfg)
    out = capsys.readouterr().out
    assert tag_calls == ["g/shop"]  # center 한 번만 · repo 는 서버로 바로 복사하는 job 이 없어 안 읽음
    was, web = sent["shapes"]["shop was"], sent["shapes"]["shop web"]
    assert {e: c["version"] for e, c in was["versions"]["build"].items()} == {"prod": "v1.0.9", "dev": "v1.0.9"}
    assert was["versions"]["deploy"] == {"prod": {"version": "v1.0.2", "tag": "prod-was-v1.0.2", "at": "2026-10-01T00:00:00Z", "job": 30, "side": "center"}}
    assert web["versions"]["build"]["prod"]["version"] == web["versions"]["deploy"]["prod"]["version"] == "v2.1.0"  # web tag 는 web 것만
    assert was["repo"]["project"] == "g/shop-was" and was["repo"]["build"][0]["version"] == "20"
    assert was["repo"]["code"] == {"node": "22", "node_from": ".nvmrc", "node_rule": "exact", "nest": "10.3.0"}
    assert "빌드·배포 버전: 2개 서비스" in out
    # --source local(API 안 씀) → 버전은 '모름'(키 없음), tag job 도 안 읽음
    tag_calls.clear()
    (tmp_path / "c.yml").write_text(center_ci)
    targets.write_text("services:\n  - {name: shop web, type: web, center_ci: {file: c.yml}}\n")
    cli.cmd_shape(cfg, source="local")
    assert tag_calls == [] and "versions" not in sent["shapes"]["shop web"]


def test_versions_of_prefers_repo_where_repo_copies_directly(monkeypatch):
    """repo 가 서버로 바로 복사하는 환경(dev)은 빌드·배포 모두 repo job 의 tag — center 에 옛 dev 이미지가 있어도.
    나머지 환경(prod)은 center 먼저."""
    import types

    import runner.cli as cli

    tag_jobs = {
        "g/site": [{"id": 9, "name": "build", "ref": "prod-web-v1.0.2"}, {"id": 2, "name": "build", "ref": "dev-web-v0.1.6"}],
        "g/site-src": [{"id": 50, "name": "deploy-dev", "ref": "dev-web-v1.0.2"}],
    }
    monkeypatch.setattr(cli, "fetch_tag_jobs", lambda u, t, p, timeout=8: tag_jobs[p])
    cfg = types.SimpleNamespace(gitlab_url="http://repo", gitlab_token="t", gitlab_center_url="http://center", gitlab_center_token="t", connect_timeout=1)
    cis = {
        "repo": {"jobs": {"deploy-dev": {"kind": "direct"}, "push_src": {"kind": "push"}}},
        "center": {"jobs": {"build": {"kind": "build_image"}}},
    }
    row = {"data": {"deploy": {"dev": {"path": "direct", "by": "repo"}, "prod": {"path": "image"}}}}
    api = {"repo": ("g/site-src", None), "center": ("g/site", None)}
    v = cli._versions_of({"name": "site web", "type": "web"}, row, cis, api, {}, cfg, {})
    assert (v["build"]["dev"]["version"], v["build"]["dev"]["side"]) == ("v1.0.2", "repo")
    assert (v["deploy"]["dev"]["version"], v["deploy"]["dev"]["side"]) == ("v1.0.2", "repo")
    assert (v["build"]["prod"]["version"], v["build"]["prod"]["side"]) == ("v1.0.2", "center") and "prod" not in v["deploy"]


def test_parse_build_log_versions():
    """shell 러너 빌드 — CI 에 image: 가 없어 버전이 파일에 없을 때 build job 로그에 찍힌 흔적."""
    assert parse_build_log_versions("npm WARN EBADENGINE   current: { node: 'v20.15.1', npm: '10.2.5' }") == {"node": "20.15.1"}
    assert parse_build_log_versions('$ java -version\nopenjdk version "17.0.14" 2025-01-21\n') == {"java": "17"}
    assert parse_build_log_versions('java version "1.8.0_381"') == {"java": "8"}  # 1.8 = 8
    assert parse_build_log_versions("\x1b[32;1m$ node -v\x1b[0;m\nv22.11.0\n") == {"node": "22.11.0"}  # 색 코드 지움
    assert parse_build_log_versions("Now using node v18.20.4 (npm v10.8.2)") == {"node": "18.20.4"}
    assert parse_build_log_versions("Done in 14.6s using pnpm v10.17.0") == {} and parse_build_log_versions(None) == {}


def test_cmd_shape_reads_shell_build_versions_from_job_logs(monkeypatch, tmp_path, capsys):
    """repo CI 에 런타임 이미지가 없으면(shell 러너) 최근 성공한 build job 로그에서 node·java 를 읽는다.
    로그에 버전 줄이 없는 서비스는 같은 러너(같은 서버)에서 본 값을 '추정' 으로 쓴다."""
    import types

    import runner.cli as cli

    repo_ci = "variables: {RUNNER_TAG: shell-runner}\nbuild:\n  tags: [$RUNNER_TAG]\n  script: [npm install, npm run build]\npush_src:\n  script: [git push origin HEAD:main]\n"
    targets = tmp_path / "shape-targets.yml"
    targets.write_text(
        "services:\n"
        "  - {name: site web, type: web, repo: g/site}\n"
        "  - {name: shop web, type: web, repo: g/shop}\n"
    )
    sent: dict = {}

    class FakeAPI:
        def __init__(self, *a):
            pass

        def upload_shapes(self, shapes, replace=False):
            sent["shapes"] = {s["service"]: s["data"] for s in shapes}
            return {"accepted": len(shapes), "removed": 0}

        def close(self):
            pass

    jobs = {
        "g/site": [{"id": 31, "name": "build", "status": "success", "runner_id": 7, "runner_name": "shell-01", "web_url": ""}],
        "g/shop": [
            {"id": 42, "name": "push_src", "status": "success", "runner_id": 7, "runner_name": "shell-01", "web_url": ""},
            {"id": 41, "name": "build", "status": "success", "runner_id": 7, "runner_name": "shell-01", "web_url": ""},
        ],
    }
    logs = {31: "npm WARN EBADENGINE   current: { node: 'v20.15.1', npm: '10.2.5' }\n", 41: "Done in 14.6s using pnpm v10.17.0\n"}
    read: list[int] = []
    monkeypatch.setattr(cli, "CentralAPI", FakeAPI)
    monkeypatch.setattr(cli, "fetch_repo_file", lambda u, t, p, path, ref="", timeout=8: repo_ci if path == ".gitlab-ci.yml" else None)
    monkeypatch.setattr(cli, "fetch_recent_jobs", lambda u, t, p, timeout=8: jobs[p])
    monkeypatch.setattr(cli, "fetch_job_log_head", lambda u, t, p, jid, timeout=8, max_bytes=20000: read.append(jid) or logs.get(jid, ""))
    monkeypatch.setattr(cli, "build_row", lambda spec, files, runners=None: _row_with_runtime(spec, files, runners))
    cfg = types.SimpleNamespace(
        shape_targets=str(targets), central_url="x", api_token="t", gitlab_url="http://repo", gitlab_token="tok",
        gitlab_center_url="", gitlab_center_token="", gitlab_ref="", connect_timeout=1,
    )
    cli.cmd_shape(cfg)
    out = capsys.readouterr().out
    site, shop = sent["shapes"]["site web"]["repo"], sent["shapes"]["shop web"]["repo"]
    assert site["build"] == [{"runtime": "node", "version": "20.15.1", "image": None, "jobs": ["build"], "from": "log", "job": 31, "runner": "shell-01"}]
    assert shop["build"] == [{**site["build"][0], "guess": True}]  # 로그엔 pnpm 버전뿐 → 같은 러너에서 본 node
    assert 41 in read and 42 not in read  # build job 로그만(푸시 job 은 안 읽음)
    assert "repo 빌드 버전(job 로그): 2개 (같은 러너로 추정 1)" in out


def _row_with_runtime(spec, files, runners):
    """실행 이미지가 node 인 행(로그 추정은 실행 런타임과 같은 것만 채움)."""
    row = build_row(spec, files, runners)
    row["data"].update(runtime="node", runtime_version="18")
    return row
