"""CI/CD 형상 판독기 (읽기 전용, 순수 함수) — 서비스끼리 비교하는 표의 한 행을 만든다.

읽는 파일(원문 텍스트)과 뽑는 칸:
  - repo·center `.gitlab-ci.yml` → 환경별 배포 경로(직배포/이미지/빌드만)·수동 여부, executor
  - config `Dockerfile`          → 런타임·버전, 베이스 이미지(마지막 FROM)
  - config `start.sh` · compose   → start.sh 유무, (CI 가 없을 때) 배포 경로
  - `variables:`                 → env 개수 + 해시. **값은 밖으로 안 나간다**(해시만).

executor 는 GitLab API 가 알려주지 않으므로 사람이 확인한 runners 표(tag→shell|docker)를 우선 쓰고,
표에 없는 태그면 `image:` 유무로 추정(guess=True)한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

import yaml

ENVS = ("dev", "lab", "stg", "preview", "prod")
_ENV_WORDS = {
    "dev": "dev", "develop": "dev", "development": "dev",
    "lab": "lab",
    "stg": "stg", "stage": "stg", "staging": "stg",
    "preview": "preview",
    "prod": "prod", "production": "prod",
}
_RESERVED = {
    "stages", "variables", "default", "include", "workflow", "image",
    "services", "before_script", "after_script", "cache",
}
_START_SH = re.compile(r"start[\w-]*\.sh", re.I)


# ── YAML (GitLab 의 !reference 같은 커스텀 태그는 그냥 값으로) ─────────────
class _Loader(yaml.SafeLoader):
    pass


def _any_tag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_Loader.add_multi_constructor("!", _any_tag)


def load_yaml(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        doc = yaml.load(text, Loader=_Loader)  # noqa: S506 - SafeLoader 하위 클래스
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────
def _vars(raw: Any) -> dict[str, str]:
    """variables: {K: v} 또는 {K: {value: v}} → {K: 'v'}."""
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                v = v.get("value", "")
            out[str(k)] = "" if v is None else str(v)
    return out


def _expand(s: str, env: dict[str, str]) -> str:
    for _ in range(3):  # 변수 안의 변수까지 몇 단계만
        new = re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: env.get(m.group(1) or m.group(2), m.group(0)), s)
        if new == s:
            break
        s = new
    return s


def _flatten(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [s for item in x for s in _flatten(item)]
    return [str(x)]


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _resolve(name: str, defs: dict[str, dict], depth: int = 0) -> dict:
    """extends 를 펼친 job (GitLab 처럼 hash 는 깊게 병합, 배열은 교체)."""
    job = defs.get(name)
    if not isinstance(job, dict):
        return {}
    ext = job.get("extends")
    if not ext or depth > 5:
        return job
    merged: dict = {}
    for base in [ext] if isinstance(ext, str) else _flatten(ext):
        merged = _deep_merge(merged, _resolve(base, defs, depth + 1))
    return _deep_merge(merged, {k: v for k, v in job.items() if k != "extends"})


def _gl_regex(s: str) -> re.Pattern | None:
    """GitLab 정규식 '/.../i' → Python 패턴."""
    m = re.match(r"^/(.*)/([a-z]*)$", s.strip(), re.S)
    if not m:
        return None
    try:
        return re.compile(m.group(1), re.I if "i" in m.group(2) else 0)
    except re.error:
        return None


def _env_word(*texts: Any) -> str | None:
    for t in texts:
        for w in re.split(r"[^a-z]+", str(t or "").lower()):
            if w in _ENV_WORDS:
                return _ENV_WORDS[w]
    return None


# ── .gitlab-ci.yml ───────────────────────────────────────────────────
def _job_envs(name: str, job: dict, svc_type: str) -> dict[str, bool]:
    """이 job 이 도는 환경 → 수동 여부. 태그 정규식에 '<env>-<type>-v1.0.0' 을 대 보고 판단."""
    rules: list[tuple[re.Pattern, Any]] = []
    only = job.get("only")
    refs = only.get("refs") if isinstance(only, dict) else only
    for r in _flatten(refs):
        rx = _gl_regex(r)
        if rx:
            rules.append((rx, None))
    for rule in job.get("rules") or []:
        if isinstance(rule, dict):
            for m in re.finditer(r"=~\s*(/(?:\\/|[^/])*/[a-z]*)", str(rule.get("if") or "")):
                rx = _gl_regex(m.group(1))
                if rx:
                    rules.append((rx, rule.get("when")))

    manual = job.get("when") == "manual"
    env_obj = job.get("environment")
    named = _env_word(name, env_obj.get("name") if isinstance(env_obj, dict) else env_obj)
    if not rules:
        return {named: manual} if named else {}
    hits: dict[str, tuple[int, bool]] = {}  # env → (맞은 규칙 번호, 수동?)
    for env in ENVS:
        tag = f"{env}-{svc_type}-v1.0.0"
        for idx, (rx, when) in enumerate(rules):
            if rx.search(tag):
                if when != "never":
                    hits[env] = (idx, manual or when == "manual")
                break
    if named and named in hits:
        # deploy-prod 처럼 이름에 환경이 박혀 있으면, 같은 '넓은 규칙'으로 걸린 다른 환경은 뺀다.
        # (따로 적힌 규칙 — 예: deploy-dev 안의 lab 규칙 — 은 남긴다)
        wide = hits[named][0]
        hits = {e: v for e, v in hits.items() if e == named or v[0] != wide}
    return {e: m for e, (_, m) in hits.items()}


def _strip_comments(script: str) -> str:
    """셸 주석 줄은 뺀다 — '# scp 방식으로 이전 예정' 같은 메모가 판독을 흔들지 않게."""
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


def _job_kind(name: str, job: dict, env: dict[str, str]) -> str:
    raw = "\n".join(_flatten([job.get("before_script"), job.get("script"), job.get("after_script")]))
    text = _expand(_strip_comments(raw), env)
    lname = name.lower()
    if re.search(r"\b(scp|rsync)\b", text):
        return "direct"            # 빌드 결과물을 서버로 바로 복사
    if re.search(r"\bdocker\s+push\b", text):
        return "build_image"       # 이미지 빌드·push (center)
    if re.search(r"\bgit\s+push\b", text) or "push_src" in lname or "push-src" in lname:
        return "push"              # 산출물을 center 로 넘김
    if re.search(r"\bssh\b", text) and re.search(
        r"docker[- ]compose\b[^\n]*\b(pull|up)\b|\bdocker\s+pull\b|TAG_INFO|\bkubectl\b|\bhelm\b", text
    ):
        return "deploy_image"      # 서버에서 이미지 받아 올림
    return "other"                 # 빌드·테스트·알림 등


def _image_name(v: Any) -> str | None:
    """job 의 image: 값 → 이미지 이름. {name: …, entrypoint: …} 모양도."""
    if isinstance(v, dict):
        v = v.get("name")
    return str(v) if v else None


def _executor(jobs: list[tuple[str, list[str], str | None]], runners: dict[str, str]) -> dict | None:
    """job 마다 executor 를 정하고 가장 많은 쪽을 대표로.

    jobs = [(job 이름, 그 job 의 러너 태그들, image:(없으면 None))]. 태그가 runners 표에 있으면 확정, 없으면
    image: 유무로 짐작(docker/shell). 대표값이 짐작으로만 나왔으면 guess=True.
    여러 방식이 섞이면 counts(방식별 job 수)와 groups(러너 태그별 job 목록)를 남긴다 — 화면의 '섞임' 메모용.
    """
    votes: list[tuple[str, bool]] = []  # (값, 짐작?)
    tags: set[str] = set()
    groups: dict[str, dict] = {}  # 러너 태그 → {value, guess, jobs}
    for name, jtags, image in jobs:
        has_image = bool(image)
        tags.update(jtags)
        known = [runners[t] for t in jtags if t in runners]
        if known:
            vote, why = (known[0], False), "runners 표"
        elif jtags or has_image:
            # image: 가 있으면 docker. 없으면 shell 로 짐작(docker 기본 이미지+소켓일 수도 있음 — job 로그로 확정)
            vote, why = ("docker" if has_image else "shell", True), ("image: 있음" if has_image else "image: 없음")
        else:
            continue
        votes.append(vote)
        key = ", ".join(jtags) or "(태그 없음)"
        g = groups.setdefault(key, {"tag": key, "value": vote[0], "guess": vote[1], "why": why, "jobs": [], "images": {}})
        g["jobs"].append(name)
        if image:  # 화면에서 펼치면 job 마다 어떤 이미지로 도는지
            g["images"][name] = image
    if not votes:
        return None
    return _summarize_executor(list(groups.values()), sorted(tags))


def _summarize_executor(groups: list[dict], tags: list[str]) -> dict:
    """러너 태그 그룹들 → 대표값(job 수가 가장 많은 방식), 짐작 여부, 섞였으면 방식별 job 수."""
    counts: Counter[str] = Counter()
    for g in groups:
        counts[g["value"]] += len(g["jobs"])
    value = counts.most_common(1)[0][0]
    guess = all(g["guess"] for g in groups if g["value"] == value)
    out = {"value": value, "guess": guess, "tags": tags, "groups": groups}
    if len(counts) > 1:
        out["counts"] = dict(counts)
    return out


_LOG_EXECUTOR = re.compile(r'Preparing the "([^"]+)" executor')
_LOG_IMAGE = re.compile(r"Using \S*[Dd]ocker\S* executor with image (\S+)")


def parse_executor_log(text: str | None) -> dict | None:
    """job 로그 앞부분 → {executor, raw, image?}. 'Preparing the "docker+machine" executor' 도 docker 로.

    image = docker 일 때 실제로 쓴 이미지(job 에 image: 가 없으면 러너 기본 이미지가 찍힘).
    """
    m = _LOG_EXECUTOR.search(text or "")
    if not m:
        return None
    raw = m.group(1)
    out = {"executor": "docker" if raw.startswith("docker") else raw, "raw": raw}
    im = _LOG_IMAGE.search(text or "")
    if im:
        out["image"] = im.group(1).rstrip(" .")
    return out


def confirm_executor(cell: dict | None, confirmed: dict[str, dict]) -> dict | None:
    """job 로그로 확인한 결과를 러너 태그 그룹에 덮어씀 → 대표값 다시 계산.

    confirmed: {러너 태그: {executor, job_id, default_image?}} — 확인 못 한 그룹은 그대로(추정 유지).
    """
    if not cell or not confirmed:
        return cell
    groups = []
    for g in cell.get("groups") or []:
        c = confirmed.get(g["tag"])
        if c:
            g = {**g, "value": c["executor"], "guess": False, "why": f"job 로그 #{c['job_id']}"}
            if c.get("default_image"):
                g["default_image"] = c["default_image"]  # image: 없이 도는 job 이 실제로 쓰는 러너 기본 이미지(로그에서)
        groups.append(g)
    return _summarize_executor(groups, list(cell.get("tags") or [])) if groups else cell


def analyze_ci(text: str | None, svc_type: str = "web", runners: dict[str, str] | None = None) -> dict | None:
    """환경별 job 종류(+수동 여부), executor, variables 를 뽑는다. 못 읽으면 None."""
    doc = load_yaml(text)
    if doc is None:
        return None
    top = _vars(doc.get("variables"))
    defs = {k: v for k, v in doc.items() if k not in _RESERVED and isinstance(v, dict)}
    default = doc.get("default") if isinstance(doc.get("default"), dict) else {}
    top_image = _image_name(default.get("image")) or _image_name(doc.get("image"))  # 전체 기본 이미지
    envs: dict[str, dict[str, bool]] = {}
    job_runs: list[tuple[str, list[str], str | None]] = []  # executor 판정용 (job 이름, 태그, image:)
    variables = {f"global:{k}": v for k, v in top.items()}
    for name in defs:
        if name.startswith("."):
            continue  # 숨은 템플릿(extends 대상)
        job = _resolve(name, defs)
        jvars = _vars(job.get("variables"))
        variables.update({f"{name}:{k}": v for k, v in jvars.items()})
        scope = {**top, **jvars}
        image = _image_name(job.get("image")) or top_image
        job_runs.append((name, [_expand(t, scope) for t in _flatten(job.get("tags"))], _expand(image, scope) if image else None))
        kind = _job_kind(name, job, scope)
        for env, manual in _job_envs(name, job, svc_type).items():
            slot = envs.setdefault(env, {})
            slot[kind] = manual if kind not in slot else (slot[kind] and manual)  # 자동 job 이 하나라도 있으면 자동
    return {
        "envs": envs,
        "executor": _executor(job_runs, runners or {}),
        "tags": sorted({t for _, jt, _ in job_runs for t in jt}),
        "variables": variables,
    }


# ── Dockerfile ───────────────────────────────────────────────────────
def split_image(ref: str) -> tuple[str, str | None]:
    """'reg.example.com:5000/infra/nodejs:v18' → ('infra/nodejs', 'v18'). 레지스트리 호스트는 뗀다."""
    ref = ref.split("@", 1)[0]
    parts = ref.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost" or parts[0].startswith("$")):
        parts = parts[1:]
    last = parts[-1]
    tag = None
    if ":" in last:
        last, tag = last.split(":", 1)
    return "/".join([*parts[:-1], last]), tag


def _num(s: str) -> str | None:
    m = re.match(r"v?(\d+(?:\.\d+)*)", s)
    return m.group(1) if m else None


_JAVA_IMAGES = {"openjdk", "eclipse-temurin", "temurin", "amazoncorretto", "corretto", "java", "jdk", "jre",
                "springboot", "spring-boot", "maven", "gradle"}


def detect_runtime(name: str, tag: str | None) -> tuple[str | None, str | None]:
    """베이스 이미지 이름·태그 → (런타임, 버전). 'nodejs','v18' → ('node','18')."""
    last = name.rsplit("/", 1)[-1].lower()
    t = (tag or "").lower()
    if last in ("node", "nodejs"):
        v = _num(t)
        return "node", v if v and int(v.split(".")[0]) >= 4 else None  # 사내 태그(0.0.3 등)는 버전 아님
    m = re.search(r"(?:java|jdk|jre|temurin|corretto)[-_]?(\d+)", t)
    if m:
        return "java", m.group(1)
    if last in _JAVA_IMAGES:
        return "java", _num(t) if last in ("openjdk", "eclipse-temurin", "temurin", "amazoncorretto", "corretto") else None
    if last in ("nginx", "python", "golang", "php", "ruby"):
        return ("go" if last == "golang" else last), _num(t)
    return None, None


def analyze_dockerfile(text: str | None) -> dict | None:
    if not text:
        return None
    joined = re.sub(r"\\\r?\n", " ", text)
    args: dict[str, str] = {}
    aliases: dict[str, str] = {}
    base = None
    has_cmd = copies_startup = False
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kw, _, rest = line.partition(" ")
        kw = kw.upper()
        rest = rest.strip()
        if kw == "ARG":
            k, _, v = rest.partition("=")
            args.setdefault(k.strip(), v.strip().strip('"'))
        elif kw == "FROM":
            toks = [t for t in rest.split() if not t.startswith("--")]
            if not toks:
                continue
            ref = _expand(toks[0], args)
            ref = aliases.get(ref.lower(), ref)  # FROM builder → 앞 단계의 실제 이미지
            if len(toks) >= 3 and toks[1].upper() == "AS":
                aliases[toks[2].lower()] = ref
            base = ref
        elif kw in ("CMD", "ENTRYPOINT"):
            has_cmd = True
        elif kw in ("COPY", "ADD") and _START_SH.search(rest):
            copies_startup = True
    if base is None:
        return None
    name, tag = split_image(base)
    runtime, version = detect_runtime(name, tag)
    return {
        "image": name, "tag": tag, "runtime": runtime, "runtime_version": version,
        "has_cmd": has_cmd, "copies_startup": copies_startup,
    }


# ── compose ──────────────────────────────────────────────────────────
def analyze_compose(text: str | None) -> dict | None:
    """image 태그가 변수(${TAG_INFO} 등)면 '이미지' 배포, 고정 베이스 이미지면 '직배포'(파일 넣어 띄움)."""
    doc = load_yaml(text)
    services = doc.get("services") if doc else None
    if not isinstance(services, dict):
        return None
    images: list[str] = []
    startup = command = False
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        if svc.get("image"):
            images.append(str(svc["image"]))
        if svc.get("command") or svc.get("entrypoint"):
            command = True
        for v in svc.get("volumes") or []:
            src = v.get("source", "") if isinstance(v, dict) else str(v)
            if _START_SH.search(str(src)):
                startup = True
    if not images:
        return None
    path = "image" if any("$" in i.rsplit("/", 1)[-1] for i in images) else "direct"
    # start.sh 형태: start.sh 를 마운트하면 shell(mount), command: 로 직접 실행하면 compose(command), 둘 다 없으면 Dockerfile(image)
    start = "mount" if startup else ("command" if command else "image")
    return {"path": path, "startup": startup, "start": start, "images": images}


# ── 한 행으로 합치기 ──────────────────────────────────────────────────
def _deploy_cell(env: str, repo: dict | None, center: dict | None) -> dict | None:
    """환경 하나의 배포 경로.

    direct(by=repo)   = repo CI 가 서버로 바로 복사(옛 직배포, center 안 거침)
    direct(by=center) = repo 가 center 로 넘기고, center 가 빌드 결과물을 서버로 복사(이미지 안 만듦)
    image             = center 가 만든 도커 이미지로 배포
    build             = repo 에서 빌드만 하고 끝
    """
    r = (repo or {}).get("envs", {}).get(env, {})
    c = (center or {}).get("envs", {}).get(env, {})
    if "direct" in r:
        return {"path": "direct", "by": "repo", "manual": r["direct"]}
    reaches_center = ("push" in r) if repo else True  # repo 가 이 환경을 center 로 넘기나(repo CI 없으면 center 만 봄)
    if reaches_center and "direct" in c:
        return {"path": "direct", "by": "center", "manual": c["direct"]}
    image = "push" in r if repo else ("build_image" in c or "deploy_image" in c)
    if image:
        return {"path": "image", "manual": c.get("deploy_image")}  # None = center 에 배포 job 없음
    if r:
        return {"path": "build", "manual": None}
    return None


def env_fingerprint(*cis: tuple[str, dict | None]) -> tuple[int | None, str | None]:
    """variables 개수 + 해시. 값은 해시 안에만 들어가고 밖으로 나가지 않는다."""
    items = [f"{label}|{k}={v}" for label, ci in cis if ci for k, v in ci["variables"].items()]
    if not any(ci for _, ci in cis):
        return None, None
    return len(items), hashlib.sha256("\n".join(sorted(items)).encode()).hexdigest()


def build_row(spec: dict, files: dict[str, Any], runners: dict[str, str] | None = None) -> dict:
    """spec: {name, group?, type?, tag_type?} · files: {repo_ci, center_ci, dockerfile, startup, compose: {env: text}}.

    files 값이 None 이면 '못 읽음/없음'. startup 은 키가 있고 None 이면 '파일 없음(=start.sh 없음)'.
    """
    svc_type = str(spec.get("type") or "web")
    # tag_type = 태그·폴더에 쓰는 타입이 표에 보일 타입과 다를 때(예: 표는 manager·syncer, 태그는 둘 다 app)
    ci_type = str(spec.get("tag_type") or svc_type)
    repo = analyze_ci(files.get("repo_ci"), ci_type, runners)
    center = analyze_ci(files.get("center_ci"), ci_type, runners)
    docker = analyze_dockerfile(files.get("dockerfile"))
    composes = {env: analyze_compose(t) for env, t in (files.get("compose") or {}).items()}
    composes = {env: c for env, c in composes.items() if c}

    deploy: dict[str, dict] = {}
    for env in ENVS:
        cell = _deploy_cell(env, repo, center)
        comp = composes.get(env)
        if cell is None and comp:  # CI 에 이 환경 배포가 없음 → 서버 compose 모양으로 짐작
            cell = {"path": comp["path"], "by": "compose", "manual": None}
        if cell is None:
            continue
        cell["mismatch"] = bool(comp and cell["path"] in ("direct", "image") and comp["path"] != cell["path"])
        deploy[env] = cell

    startup: bool | None = None
    if "startup" in files or docker or composes:
        startup = bool(
            files.get("startup")
            or (docker and docker["copies_startup"])
            or any(c["startup"] for c in composes.values())
        )

    env_keys, env_hash = env_fingerprint(("repo", repo), ("center", center))
    return {
        "service": str(spec["name"]),
        "group": spec.get("group"),
        "data": {
            "type": svc_type,
            "note": spec.get("note"),  # 표에 작게 붙는 메모(예: '옛 사본')
            "runtime": docker["runtime"] if docker else None,
            "runtime_version": docker["runtime_version"] if docker else None,
            "base_image": docker["image"] if docker else None,
            "base_tag": docker["tag"] if docker else None,
            "deploy": deploy,
            "executor_repo": repo["executor"] if repo else None,
            "executor_center": center["executor"] if center else None,
            "startup": startup,
            "env_keys": env_keys,
        },
        "env_hash": env_hash,
    }


# ── center config repo (<서비스>/<web|was>/ 폴더 하나 = 한 행) ─────────────
def is_dockerfile(name: str) -> bool:
    n = name.lower()
    return n == "dockerfile" or n.startswith("dockerfile.") or n.endswith(".dockerfile")


def analyze_config_dir(names: list[str], dockerfile_text: str | None) -> dict:
    """config 폴더 하나 판독. names = 폴더 안 파일 이름들, dockerfile_text = Dockerfile 원문(없으면 None).

    처음 실행할 명령 — 이미지 기준(start):
      dockerfile = Dockerfile 에 CMD/ENTRYPOINT 가 있음(이미지가 스스로 실행)
      start.sh   = CMD 없이 start.sh 를 이미지에 넣어(COPY) 그걸로 실행
      server     = CMD 도 없고 start.sh 도 안 넣음(파일만 폴더에 있음) → 이미지 혼자 못 띄움, 서버가 명령을 줘야 함
      base       = 아무것도 없음 → 베이스 이미지 기본값(예: springboot)
    정리할 것(state): legacy(start.sh → CMD 로 옮기기) / leftover(CMD 로 뜨는데 start.sh 파일이 남음 → 지우기) /
                     server(Dockerfile 에 CMD 넣기) / done / base / none(Dockerfile 없음)
    """
    sh_files = sorted(n for n in names if _START_SH.search(n))
    docker = analyze_dockerfile(dockerfile_text)
    if docker is None:
        start, state = None, "none"
    elif docker["has_cmd"]:
        start, state = "dockerfile", ("leftover" if sh_files else "done")
    elif docker["copies_startup"]:
        start, state = "start.sh", "legacy"
    elif sh_files:
        start, state = "server", "server"
    else:
        start, state = "base", "base"
    return {
        "runtime": docker["runtime"] if docker else None,
        "runtime_version": docker["runtime_version"] if docker else None,
        "base_image": docker["image"] if docker else None,
        "base_tag": docker["tag"] if docker else None,
        "start": start,
        "start_files": sh_files,
        "state": state,
    }


def config_dirs(paths: list[str]) -> dict[str, list[str]]:
    """repo 안 파일 경로들 → {'<서비스>/<타입>': [파일 이름…]}.

    보통은 깊이 3(서비스/타입/파일). 타입 없이 '<서비스>/Dockerfile' 로 바로 둔 곳(예: bot/Dockerfile)도 한 행으로 —
    단 그 폴더에 Dockerfile 이 있을 때만(README 같은 파일로 빈 행이 생기지 않게).
    """
    out: dict[str, list[str]] = {}
    flat: dict[str, list[str]] = {}
    for p in paths:
        parts = p.strip("/").split("/")
        if parts[0].startswith("."):
            continue
        if len(parts) == 3:
            out.setdefault(f"{parts[0]}/{parts[1]}", []).append(parts[2])
        elif len(parts) == 2:
            flat.setdefault(parts[0], []).append(parts[1])
    for svc, names in flat.items():
        if any(is_dockerfile(n) for n in names):
            out[svc] = names
    return out


# ── 코드에 적힌 버전(repo 의 .nvmrc · package.json · pom.xml) ─────────────
def code_versions(files: dict[str, str | None]) -> dict:
    """repo 코드가 '이 버전으로 빌드해라' 고 적어 둔 값.

    node: .nvmrc(정확한 버전) 우선, 없으면 package.json engines.node('>=20' 은 최소 버전 → rule=min).
    nest: @nestjs/core, java: pom.xml. 값이 하나도 없으면 빈 dict.
    """
    from .repoversions import _ver_or_major, parse_nvmrc, parse_pom_java

    out: dict = {}
    nvm = parse_nvmrc(files.get(".nvmrc") or "")
    pkg: dict = {}
    try:
        loaded = json.loads(files.get("package.json") or "{}")
        pkg = loaded if isinstance(loaded, dict) else {}
    except ValueError:
        pkg = {}
    engines = str((pkg.get("engines") or {}).get("node") or "")
    if nvm:
        out.update(node=nvm, node_from=".nvmrc", node_rule="exact")
    elif _ver_or_major(engines):
        rule = "min" if engines.strip().startswith(">") else "exact"
        out.update(node=_ver_or_major(engines), node_from="package.json", node_rule=rule)
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    nest = _ver_or_major(deps.get("@nestjs/core"))
    if nest:
        out["nest"] = nest
    java = parse_pom_java(files.get("pom.xml") or "")
    if java:
        out["java"] = java
    return out


# ── center CI 에서 '어느 서버의 어느 폴더로 배포하나' 읽기(서버 compose 자동 읽기용) ──────────
_SERVERS_VAR = re.compile(r"DEPLOY_(DEV|LAB|STG|STAGE|PREVIEW|PRIVIEW|PROD)(?:_([A-Z]+))?_SERVERS?$")
_ENV_KEY = {"DEV": "dev", "LAB": "lab", "STG": "stg", "STAGE": "stg", "PREVIEW": "preview", "PRIVIEW": "preview", "PROD": "prod"}


def _expand_shell(s: str, env: dict[str, str]) -> str:
    """셸 변수 펼치기: \\${X} → ${X}, ${X:-기본값}, ${X}, $X. 모르는 변수는 그대로 둔다."""
    s = s.replace("\\$", "$")
    for _ in range(5):
        new = re.sub(
            r"\$\{(\w+):-([^{}]*)\}",
            lambda m: env.get(m.group(1)) or m.group(2),
            s,
        )
        new = re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: env.get(m.group(1) or m.group(2), m.group(0)), new)
        if new == s:
            break
        s = new
    return s


def deploy_targets(text: str | None, svc_type: str = "web", role: str | None = None) -> dict[str, dict]:
    """center CI → {env: {"hosts": [주소…], "dir": "/app/…"}}.

    서버: variables 의 DEPLOY_<ENV>[_<TYPE>]_SERVERS (타입이 맞는 게 우선, 없으면 타입 없는 것).
      role = 같은 이미지를 역할별 서버에 나눠 까는 경우(예: prod 만 MGR·WRK 서버로 나눔) —
      DEPLOY_<ENV>_<ROLE>_SERVERS 가 가장 우선. 폴더(BUILD_INFO)는 그대로 svc_type.
    폴더: 스크립트의 APP_DIR="…" (주석 줄 제외) 를 SERVICE_INFO·BUILD_INFO(=타입)로 펼침. 못 펼치면 dir 없음.
    """
    doc = load_yaml(text)
    if doc is None:
        return {}
    top = _vars(doc.get("variables"))
    picked: dict[str, tuple[int, list[str]]] = {}  # env → (우선순위, 주소들)
    for k, v in top.items():
        m = _SERVERS_VAR.match(k)
        hosts = [h for h in re.split(r"[,\s]+", v.strip()) if h]
        if not m or not hosts:
            continue
        env, typ = _ENV_KEY[m.group(1)], (m.group(2) or "").lower()
        if typ and typ not in (svc_type, role):
            continue
        rank = 0 if role and typ == role else 1 if typ == svc_type else 2
        if env not in picked or rank < picked[env][0]:
            picked[env] = (rank, hosts)
    # 환경마다 규칙(rules) 안에서 따로 넣는 변수 — 예: lab 태그일 때만 APP_DIR_OVERRIDE: /app/web-lab
    env_vars: dict[str, dict[str, str]] = {}
    for job in doc.values():
        if not isinstance(job, dict):
            continue
        for rule in job.get("rules") or []:
            if not (isinstance(rule, dict) and isinstance(rule.get("variables"), dict)):
                continue
            for m in re.finditer(r"=~\s*(/(?:\\/|[^/])*/[a-z]*)", str(rule.get("if") or "")):
                rx = _gl_regex(m.group(1))
                for env in ENVS:
                    if rx and rx.search(f"{env}-{svc_type}-v1.0.0"):
                        env_vars.setdefault(env, {}).update(_vars(rule["variables"]))
    dir_lines = [m.group(1) for line in _strip_comments(text or "").splitlines() if (m := re.search(r'\bAPP_DIR="([^"]+)"', line))]

    def app_dir(env: str) -> str | None:
        scope = {**top, "BUILD_INFO": svc_type, **env_vars.get(env, {})}
        for raw in dir_lines:
            d = _expand_shell(raw, scope)
            if d.startswith("/") and "$" not in d:
                return d.rstrip("/")
        return None

    return {env: {"hosts": hosts, "dir": app_dir(env)} for env, (_, hosts) in picked.items()}


def parse_gateways(text: str) -> tuple[dict[str, str], str | None]:
    """shape-targets.yml 의 gateways: (환경 → gw 별칭)와 gateway_user(선택). 배포 서버가 ~/.ssh/config 에 직접
    없을 때 이 gw 를 거쳐 읽는다."""
    doc = yaml.safe_load(text) or {}
    gws = {str(k): str(v) for k, v in (doc.get("gateways") or {}).items() if v}
    user = doc.get("gateway_user")
    return gws, (str(user) if user else None)


def parse_gateway_sudo(text: str) -> set[str]:
    """shape-targets.yml 의 gateway_sudo: — 안쪽 서버가 gw 의 root 계정 ssh 설정에만 등록된 gw 들.
    이 gw 에서는 `sudo -n` 으로 root 의 ssh 설정·키를 써서 읽는다(읽기만, cat)."""
    doc = yaml.safe_load(text) or {}
    return {str(g) for g in (doc.get("gateway_sudo") or [])}


def parse_targets(text: str) -> tuple[dict[str, str], list[dict], dict | None]:
    """shape-targets.yml → (runners 표, 서비스 목록, config 섹션)."""
    doc = yaml.safe_load(text) or {}
    runners = {str(k): str(v) for k, v in (doc.get("runners") or {}).items()}
    services = [s for s in (doc.get("services") or []) if isinstance(s, dict) and s.get("name")]
    config = doc.get("config") if isinstance(doc.get("config"), dict) else None
    return runners, services, config
