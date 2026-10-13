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
    out: dict[str, bool] = {}
    if rules:
        for env in ENVS:
            tag = f"{env}-{svc_type}-v1.0.0"
            for rx, when in rules:
                if rx.search(tag):
                    if when != "never":
                        out[env] = manual or when == "manual"
                    break
        if named and named in out:  # deploy-prod 처럼 이름에 환경이 박혀 있으면 그 환경만
            out = {named: out[named]}
    elif named:
        out[named] = manual
    return out


def _job_kind(name: str, job: dict, env: dict[str, str]) -> str:
    text = _expand("\n".join(_flatten([job.get("before_script"), job.get("script"), job.get("after_script")])), env)
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


def _executor(tags: list[str], uses_image: bool, runners: dict[str, str]) -> dict | None:
    known = [runners[t] for t in tags if t in runners]
    if known:
        return {"value": Counter(known).most_common(1)[0][0], "guess": False}
    if not tags and not uses_image:
        return None
    return {"value": "docker" if uses_image else "shell", "guess": True}


def analyze_ci(text: str | None, svc_type: str = "web", runners: dict[str, str] | None = None) -> dict | None:
    """환경별 job 종류(+수동 여부), executor, variables 를 뽑는다. 못 읽으면 None."""
    doc = load_yaml(text)
    if doc is None:
        return None
    top = _vars(doc.get("variables"))
    defs = {k: v for k, v in doc.items() if k not in _RESERVED and isinstance(v, dict)}
    default = doc.get("default") if isinstance(doc.get("default"), dict) else {}
    uses_image = bool(doc.get("image") or default.get("image"))
    envs: dict[str, dict[str, bool]] = {}
    tags: list[str] = []
    variables = {f"global:{k}": v for k, v in top.items()}
    for name in defs:
        if name.startswith("."):
            continue  # 숨은 템플릿(extends 대상)
        job = _resolve(name, defs)
        jvars = _vars(job.get("variables"))
        variables.update({f"{name}:{k}": v for k, v in jvars.items()})
        scope = {**top, **jvars}
        tags += [_expand(t, scope) for t in _flatten(job.get("tags"))]
        uses_image = uses_image or bool(job.get("image"))
        kind = _job_kind(name, job, scope)
        for env, manual in _job_envs(name, job, svc_type).items():
            slot = envs.setdefault(env, {})
            slot[kind] = manual if kind not in slot else (slot[kind] and manual)  # 자동 job 이 하나라도 있으면 자동
    return {
        "envs": envs,
        "executor": _executor(tags, uses_image, runners or {}),
        "tags": sorted(set(tags)),
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
    startup = False
    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        if svc.get("image"):
            images.append(str(svc["image"]))
        for v in svc.get("volumes") or []:
            src = v.get("source", "") if isinstance(v, dict) else str(v)
            if _START_SH.search(str(src)):
                startup = True
    if not images:
        return None
    path = "image" if any("$" in i.rsplit("/", 1)[-1] for i in images) else "direct"
    return {"path": path, "startup": startup, "images": images}


# ── 한 행으로 합치기 ──────────────────────────────────────────────────
def _deploy_cell(env: str, repo: dict | None, center: dict | None) -> dict | None:
    r = (repo or {}).get("envs", {}).get(env, {})
    c = (center or {}).get("envs", {}).get(env, {})
    if "direct" in r:
        return {"path": "direct", "manual": r["direct"]}
    image = "push" in r if repo else ("build_image" in c or "deploy_image" in c)
    if image:
        return {"path": "image", "manual": c.get("deploy_image")}  # None = center 에 배포 job 없음
    if "direct" in c:
        return {"path": "direct", "manual": c["direct"]}
    if r:
        return {"path": "build", "manual": None}  # repo 에서 빌드만 하고 끝
    return None


def env_fingerprint(*cis: tuple[str, dict | None]) -> tuple[int | None, str | None]:
    """variables 개수 + 해시. 값은 해시 안에만 들어가고 밖으로 나가지 않는다."""
    items = [f"{label}|{k}={v}" for label, ci in cis if ci for k, v in ci["variables"].items()]
    if not any(ci for _, ci in cis):
        return None, None
    return len(items), hashlib.sha256("\n".join(sorted(items)).encode()).hexdigest()


def build_row(spec: dict, files: dict[str, Any], runners: dict[str, str] | None = None) -> dict:
    """spec: {name, group?, type?} · files: {repo_ci, center_ci, dockerfile, startup, compose: {env: text}}.

    files 값이 None 이면 '못 읽음/없음'. startup 은 키가 있고 None 이면 '파일 없음(=start.sh 없음)'.
    """
    svc_type = str(spec.get("type") or "web")
    repo = analyze_ci(files.get("repo_ci"), svc_type, runners)
    center = analyze_ci(files.get("center_ci"), svc_type, runners)
    docker = analyze_dockerfile(files.get("dockerfile"))
    composes = {env: analyze_compose(t) for env, t in (files.get("compose") or {}).items()}
    composes = {env: c for env, c in composes.items() if c}

    deploy: dict[str, dict] = {}
    for env in ENVS:
        cell = _deploy_cell(env, repo, center)
        comp = composes.get(env)
        if cell is None and comp:
            cell = {"path": comp["path"], "manual": None}
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


def parse_targets(text: str) -> tuple[dict[str, str], list[dict]]:
    """shape-targets.yml → (runners 표, 서비스 목록)."""
    doc = yaml.safe_load(text) or {}
    runners = {str(k): str(v) for k, v in (doc.get("runners") or {}).items()}
    services = [s for s in (doc.get("services") or []) if isinstance(s, dict) and s.get("name")]
    return runners, services
