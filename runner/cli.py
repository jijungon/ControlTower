"""러너 CLI (Phase 0).

  python -m runner.cli import   # ~/.ssh/config 파싱 → 중앙 인벤토리에 임포트
  python -m runner.cli test     # 등록 서버에 SSH 연결 테스트 → 결과 업로드
  python -m runner.cli probe    # 접속 점검(접속 여부 + 2FA 추정) [--group/--host]
  python -m runner.cli conf     # 관리 경로 conf 수집 → 드리프트 비교
  python -m runner.cli updates  # 서버별 대기 OS 패치(apt, 없으면 yum/dnf) 수집
  python -m runner.cli versions # 빌드 서버 툴체인 버전(node/java/docker 등) 수집
  python -m runner.cli versions-repo # GitLab repo 선언본 버전 수집(CT_GITLAB_URL/TOKEN)
  python -m runner.cli cicd     # GitLab 파이프라인 상태 수집(CT_GITLAB_URL/TOKEN)
  python -m runner.cli shape    # 서비스 비교표 + center config(start.sh 상태·형태) 수집(shape-targets.yml)
  python -m runner.cli all      # 모든 수집기 1회(--loop --interval N 로 주기 실행)
  python -m runner.cli apply    # 승인된 conf 를 서버에 실제 적용(--dry-run/--rollback ID)

env: CT_CENTRAL_URL(기본 :8000) · CT_API_TOKEN(기본 dev-runner-token) · CT_SSH_CONFIG(기본 ~/.ssh/config)
접속 테스트는 시스템 ssh 가 ~/.ssh/config(ProxyJump·키)를 그대로 사용한다.
"""
from __future__ import annotations

import argparse
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from . import applier
from .api import CentralAPI
from .apt import parse_upgradable
from .cishape import (
    BUILD_KINDS,
    DEPLOY_KINDS,
    analyze_ci,
    analyze_compose,
    analyze_config_dir,
    build_row,
    code_versions,
    config_dirs,
    confirm_executor,
    deploy_targets,
    is_dockerfile,
    parse_build_log_versions,
    parse_executor_log,
    parse_gateway_sudo,
    parse_gateways,
    parse_targets,
    pick_versions,
)
from .config import RunnerConfig
from .conn import gateway_aliases, list_upgrades, list_upgrades_yum, read_file, read_file_via, run_remote, test_ssh
from .gitlab import (
    fetch_job_log_head,
    fetch_latest_pipeline,
    fetch_recent_jobs,
    fetch_repo_dir,
    fetch_repo_file,
    fetch_repo_tree,
    fetch_tag_jobs,
    is_down,
    reset_down,
)
from .hoststatus import read_status, summary
from .probe import probe_ssh
from .repoversions import extract_versions
from .sshconf import parse_ssh_config
from .versions import PROBES, parse_version
from .yum import parse_yum

# 선언본 후보 파일(있는 것만 파싱)
REPO_VERSION_FILES = (".nvmrc", "package.json", "pom.xml")


def _select(servers: list, group: str | None, host: str | None, online: bool = False) -> list:
    """수집/점검 대상 좁히기 — --group(그룹명) / --host(별칭) / --online(접속된 것만). 없으면 전체."""
    out = servers
    if group:
        out = [s for s in out if s.get("group") == group]
    if host:
        out = [s for s in out if s.get("hostname") == host]
    if online:
        out = [s for s in out if s.get("status") == "online"]
    return out


def cmd_import(cfg: RunnerConfig, dry_run: bool = False) -> None:
    hosts = parse_ssh_config(cfg.ssh_config)
    servers = [
        {
            "hostname": h.alias,
            "ip": h.hostname,
            "ssh_user": h.user or "",
            "ssh_port": h.port,
            "gateway_alias": h.proxy_jump,
            "credential_alias": os.path.basename(h.identity_file) if h.identity_file else None,
        }
        for h in hosts
    ]
    if dry_run:
        print(f"[dry-run] {len(servers)}개 호스트 (전송 안 함) — {cfg.ssh_config}:")
        for s in servers:
            print(f"  - {s['hostname']}  {s['ip'] or ''}  {s['ssh_user']}  key={s['credential_alias'] or '-'}")
        return
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        res = api.import_servers(servers)
        print(f"임포트: 신규 {res['imported_new']} / 총 {res['total']}개 ({cfg.ssh_config})")
    finally:
        api.close()


def cmd_test(cfg: RunnerConfig, group: str | None = None, host: str | None = None, online: bool = False) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = _select(api.list_servers(), group, host, online)
        results = []
        for s in servers:
            t0 = time.monotonic()
            ok, err = test_ssh(s["hostname"], cfg.connect_timeout)
            results.append(
                {
                    "server_id": s["id"],
                    "ok": ok,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                    "error": None if ok else err,
                }
            )
        ok_n = sum(1 for r in results if r["ok"])
        print(f"연결 테스트: {ok_n}/{len(results)} OK")
        for s, r in zip(servers, results):
            if not r["ok"]:
                print(f"  ✗ {s['hostname']}: {r['error']}")
        if results:
            api.post_connection_tests(results)
    finally:
        api.close()


def cmd_conf(cfg: RunnerConfig, group: str | None = None, host: str | None = None, online: bool = False) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = _select(api.list_servers(), group, host, online)
        paths = api.list_conf_targets()
        if not paths:
            print("관리 대상 conf 경로가 없습니다 — 먼저 추가: POST /api/conf/targets {path}")
            return
        snaps = []
        for s in servers:
            for p in paths:
                content, err = read_file(s["hostname"], p, cfg.connect_timeout)
                snaps.append({"server_id": s["id"], "path": p, "content": content, "error": err})
        res = api.upload_conf_snapshots(snaps)
        print(f"conf 수집: {res['accepted']}건 (서버 {len(servers)} × 경로 {len(paths)})")
    finally:
        api.close()


def cmd_updates(cfg: RunnerConfig, group: str | None = None, host: str | None = None, online: bool = False) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = _select(api.list_servers(), group, host, online)
        snaps = []
        for s in servers:
            out, err = list_upgrades(s["hostname"], cfg.connect_timeout)
            if out is not None:
                pkgs = parse_upgradable(out)
            elif err and "not found" in err.lower():   # apt 없음 → yum/dnf 폴백
                yout, yerr = list_upgrades_yum(s["hostname"], cfg.connect_timeout)
                if yout is not None:
                    pkgs, err = parse_yum(yout), None
                else:
                    pkgs, err = None, yerr
            else:
                pkgs = None
            snaps.append({"server_id": s["id"], "packages": pkgs, "error": err})
        res = api.upload_update_snapshots(snaps)
        pending = sum(len(x["packages"]) for x in snaps if x["packages"])
        security = sum(1 for x in snaps if x["packages"] for p in x["packages"] if p["security"])
        print(f"업데이트 수집: {res['accepted']}대 · 대기 {pending}건(보안 {security}) ")
        for s, x in zip(servers, snaps):
            if x["error"]:
                print(f"  ✗ {s['hostname']}: {x['error']}")
    finally:
        api.close()


def cmd_versions(cfg: RunnerConfig, group: str | None = None, host: str | None = None, online: bool = False) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = _select(api.list_servers(), group, host, online)
        snaps = []
        for s in servers:
            for tool, command in PROBES.items():
                raw, err = run_remote(s["hostname"], command, cfg.connect_timeout)
                if err is not None:
                    continue  # 미설치/접속 실패 툴은 건너뜀(노이즈 방지)
                ver = parse_version(tool, raw or "")
                if ver:
                    snaps.append({"server_id": s["id"], "tool": tool, "version": ver})
        res = api.upload_tool_snapshots(snaps)
        print(f"버전 수집: {res['accepted']}건 (서버 {len(servers)} × 툴 {len(PROBES)})")
    finally:
        api.close()


def cmd_versions_repo(cfg: RunnerConfig) -> None:
    if not cfg.gitlab_url or not cfg.gitlab_token:
        print("GitLab 미설정 — CT_GITLAB_URL / CT_GITLAB_TOKEN 을 설정하세요.")
        return
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        targets = api.list_version_repo_targets()
        if not targets:
            print("선언본 대상 없음 — 먼저 추가: POST /api/versions/repo-targets {repo, project}")
            return
        snaps = []
        for t in targets:
            files = {
                p: fetch_repo_file(cfg.gitlab_url, cfg.gitlab_token, t["project"], p, cfg.gitlab_ref, cfg.connect_timeout)
                for p in REPO_VERSION_FILES
            }
            for tool, ver in extract_versions(files).items():
                snaps.append({"repo": t["repo"], "tool": tool, "version": ver})
        res = api.upload_repo_snapshots(snaps)
        print(f"선언본 버전 수집: {res['accepted']}건 (repo {len(targets)})")
    finally:
        api.close()


def cmd_cicd(cfg: RunnerConfig) -> None:
    if not cfg.gitlab_url or not cfg.gitlab_token:
        print("GitLab 미설정 — CT_GITLAB_URL / CT_GITLAB_TOKEN 을 설정하세요.")
        return
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        targets = api.list_cicd_targets()
        if not targets:
            print("CI/CD 대상 없음 — 먼저 추가: POST /api/cicd/targets {service, project}")
            return
        statuses = []
        for t in targets:
            pipe = fetch_latest_pipeline(cfg.gitlab_url, cfg.gitlab_token, t["project"], cfg.connect_timeout)
            if pipe is None:
                statuses.append({"service": t["service"], "has_cicd": False})
            else:
                statuses.append({
                    "service": t["service"],
                    "has_cicd": True,
                    "status": pipe["status"],
                    "ref": pipe.get("ref"),
                    "sha": pipe.get("sha"),
                    "web_url": pipe.get("web_url"),
                })
        res = api.upload_cicd_status(statuses)
        ok = sum(1 for s in statuses if s.get("has_cicd"))
        print(f"CI/CD 수집: {res['accepted']}개 서비스 (파이프라인 {ok})")
    finally:
        api.close()


def _gitlab_of(src: dict, cfg: RunnerConfig) -> tuple[str, str]:
    if src.get("gitlab") == "center":
        return cfg.gitlab_center_url, cfg.gitlab_center_token
    return cfg.gitlab_url, cfg.gitlab_token


def _read_source(src: object, cfg: RunnerConfig, base_dir: str) -> tuple[bool, str | None]:
    """비교표 소스 1개 읽기 → (읽기 시도함?, 원문|None).

    {file: 경로}(대상 파일 기준 상대경로 가능) · {gitlab: repo|center, project, path, ref?} · {ssh: 호스트별칭, path}
    · {ssh: gw 에 등록된 이름, via: gw 별칭, path, sudo?} (gw 를 거쳐 읽기, sudo = gw 의 root 설정으로).
    해당 GitLab 이 설정 안 돼 있으면 (False, None) — '없음'과 '못 봄'을 구분하려고.
    """
    if not isinstance(src, dict):
        return False, None
    if src.get("file"):
        path = os.path.join(base_dir, os.path.expanduser(str(src["file"])))
        try:
            with open(path, encoding="utf-8") as f:
                return True, f.read()
        except OSError:
            return True, None
    if src.get("ssh") and src.get("path") and src.get("via"):  # gw 를 거쳐 안쪽 서버의 파일
        content, _err = read_file_via(str(src["via"]), str(src["ssh"]), str(src["path"]), cfg.connect_timeout, None, bool(src.get("sudo")))
        return True, content
    if src.get("ssh") and src.get("path"):  # 서버에 있는 실제 파일(예: compose) — 내용은 판독만, 중앙엔 안 올림
        content, _err = read_file(str(src["ssh"]), str(src["path"]), cfg.connect_timeout)
        return True, content
    url, token = _gitlab_of(src, cfg)
    if not url or not token or not src.get("project") or not src.get("path"):
        return False, None
    text = _memo(
        "file", fetch_repo_file,
        url, token, str(src["project"]), str(src["path"]), str(src.get("ref") or cfg.gitlab_ref or ""), cfg.connect_timeout,
    )
    return True, text


def _code_files(repo_src: object, cfg: RunnerConfig, base_dir: str) -> dict[str, str | None]:
    """repo CI 옆의 버전 파일들(.nvmrc · package.json · pom.xml · build.gradle…). GitLab 이면 폴더 목록을 한 번 보고
    있는 파일만 읽는다 — 없는 파일을 하나씩 불러 404 를 받던 것이 수집이 느린 큰 이유였음."""
    if isinstance(repo_src, dict) and repo_src.get("gitlab") and repo_src.get("project") and not repo_src.get("file"):
        url, token = _gitlab_of(repo_src, cfg)
        if url and token:
            d = os.path.dirname(str(repo_src.get("path") or ""))
            ref = str(repo_src.get("ref") or cfg.gitlab_ref or "")
            names = _memo("dir", fetch_repo_dir, url, token, str(repo_src["project"]), d, ref, cfg.connect_timeout)
            if names is not None:
                return {n: (_read_source(_sibling(repo_src, n), cfg, base_dir)[1] if n in names else None) for n in CODE_VERSION_FILES}
    return {n: _read_source(_sibling(repo_src, n), cfg, base_dir)[1] for n in CODE_VERSION_FILES}


def _sibling(src: object, name: str) -> dict | None:
    """같은 repo 의 다른 파일을 가리키는 소스(예: .gitlab-ci.yml 옆의 .nvmrc)."""
    if not isinstance(src, dict):
        return None
    if src.get("file"):
        return {**src, "file": os.path.join(os.path.dirname(os.path.expanduser(str(src["file"]))), name)}
    if src.get("path") is not None:
        d = os.path.dirname(str(src["path"]))
        return {**src, "path": f"{d}/{name}" if d else name}
    return None


CODE_VERSION_FILES = (".nvmrc", "package.json", "pom.xml", "build.gradle", "build.gradle.kts")


# 한 번 수집(shape)하는 동안 같은 GitLab 호출은 한 번만 — 미리 읽기(동시에) 결과와 같은 프로젝트의 job 목록을 다시 씀.
# 수집이 끝나면 비움(다음 수집은 새로 읽음). None 이면 꺼짐(직접 부를 때 = 예전 그대로).
_MEMO: dict | None = None
_MEMO_LOCK = threading.Lock()
GITLAB_WORKERS = 8  # 미리 읽을 때 동시에 부르는 수 — GitLab 에 무리 가지 않게


def _memo(name: str, fn: Any, *args: Any, **kw: Any) -> Any:
    if _MEMO is None:
        return fn(*args, **kw)
    key = (name, args, tuple(sorted(kw.items())))
    with _MEMO_LOCK:
        if key in _MEMO:
            return _MEMO[key]
    val = fn(*args, **kw)
    with _MEMO_LOCK:
        return _MEMO.setdefault(key, val)


def _src_info(src: object, note: str | None = None, auto: bool = False) -> dict:
    """화면에 '어디서 읽었나' 를 보여주기 위한 짧은 정보(파일 내용은 안 담음)."""
    if not isinstance(src, dict):
        return {"kind": "unknown"}
    if src.get("via"):  # 게이트웨이 경유(sudo = gw 의 root 설정으로)
        gw = f"{src['via']}(sudo)" if src.get("sudo") else src["via"]
        return {"kind": "ssh", "auto": auto, "via": src["via"], "where": f"{gw} → {src['ssh']}:{src.get('path')}"}
    if src.get("ssh"):
        return {"kind": "ssh", "auto": auto, "where": f"{src['ssh']}:{src.get('path')}"}
    note = src.get("note", note)  # 파일마다 note 를 달면 서비스 note 보다 우선(빈 값이면 메모 없음)
    if src.get("file"):
        return {"kind": "file", "note": note or None, "where": str(src["file"])}
    return {"kind": "gitlab", "note": note or None, "where": f"{src.get('project')}:{src.get('path')}"}


def _project_of(v: object) -> tuple[str | None, str | None]:
    """대상 파일의 repo:/center:/project: 값 → (GitLab 프로젝트 경로, ref). 'group/repo' 또는 {project, ref}."""
    if isinstance(v, dict):
        return (str(v["project"]) if v.get("project") else None), (str(v["ref"]) if v.get("ref") else None)
    return (str(v) if v else None), None


def _api_ready(side: str, cfg: RunnerConfig) -> bool:
    url, token = _gitlab_of({"gitlab": side}, cfg)
    return bool(url and token)


def _use_api(project: str | None, source: str) -> bool:
    """이 GitLab 을 API 로 읽나 — 기본(api)은 프로젝트 이름이 적힌 곳은 무조건 API, local 을 고를 때만 로컬 사본."""
    return bool(project) and source != "local"


def _pick(src: object, source: str) -> object:
    """GitLab 과 로컬 사본을 둘 다 적은 소스({gitlab, project, path, file}) → 기본은 GitLab, --source local 이면 file."""
    if not (isinstance(src, dict) and src.get("gitlab") and src.get("file")):
        return src
    if source == "local":
        return {k: v for k, v in src.items() if k not in ("gitlab", "project", "path", "ref")}
    return {k: v for k, v in src.items() if k != "file"}


def _ci_source(svc: dict, side: str, cfg: RunnerConfig, source: str) -> tuple[object, tuple[str, str | None] | None]:
    """repo/center CI 를 어디서 읽나 → (소스, API 면 (프로젝트, ref)). 대상 파일의 repo:/center: 프로젝트를 GitLab API 로,
    --source local 일 때(또는 프로젝트 이름이 없을 때)만 {side}_ci(로컬 사본). repo: false(저장소 없음)면 아무것도 안 읽음."""
    if svc.get(side) is False:
        return None, None
    project, ref = _project_of(svc.get(side))
    if _use_api(project, source):
        src: dict = {"gitlab": side, "project": project, "path": ".gitlab-ci.yml"}
        if ref:
            src["ref"] = ref
        return src, (str(project), ref)
    return svc.get(f"{side}_ci"), None


def _executor_from_logs(side: str, project: str, cell: dict | None, cfg: RunnerConfig, cache: dict) -> dict[str, dict]:
    """러너 태그 그룹마다 최근 job 하나의 로그 맨 윗줄('Preparing the "shell" executor')로 executor 를 확정.

    같은 러너(runner id)는 한 번만 읽는다(cache). 반환: {러너 태그: {executor, job_id, runner_name?, default_image?}} — 못 본 그룹은 빠짐.
    """
    if not cell or not cell.get("groups"):
        return {}
    url, token = _gitlab_of({"gitlab": side}, cfg)
    if not url or not token:
        return {}
    jobs = _memo("jobs", fetch_recent_jobs, url, token, project, cfg.connect_timeout) or []
    out: dict[str, dict] = {}
    for g in cell["groups"]:
        names = set(g["jobs"])
        job = next((j for j in jobs if j["name"] in names and j["runner_id"] and j["status"] not in ("pending", "created", "manual", "skipped")), None)
        if not job:
            continue
        key = (side, job["runner_id"])
        if key not in cache:
            parsed = parse_executor_log(_memo("log", fetch_job_log_head, url, token, project, job["id"], cfg.connect_timeout))
            if parsed:
                parsed = {
                    "executor": parsed["executor"], "job_id": job["id"], "image": parsed.get("image"), "job": job["name"],
                    "runner_name": job.get("runner_name"),
                }
            cache[key] = parsed
        hit = cache[key]
        if hit:
            # image: 없이 돈 job 의 로그에 찍힌 이미지 = 그 러너의 기본 이미지
            default = hit["image"] if hit.get("image") and hit["job"] not in (g.get("images") or {}) else None
            out[g["tag"]] = {
                "executor": hit["executor"], "job_id": hit["job_id"],
                **({"runner_name": hit["runner_name"]} if hit.get("runner_name") else {}),
                **({"default_image": default} if default else {}),
            }
    return out


def _versions_of(
    svc: dict, row: dict, cis: dict[str, dict | None], api: dict[str, tuple[str, str | None]],
    claims: dict[tuple[str, str], dict[str, set[str]]], cfg: RunnerConfig, cache: dict,
) -> dict | None:
    """환경마다 마지막으로 성공한 빌드·배포 tag (GitLab API — tag 로 돈 job). API 로 안 읽은 쪽만 있으면 None(모름).

    center 를 먼저 보고, repo 는 repo 가 서버로 바로 복사하는(direct) job 이 있을 때만 읽는다.
    claims[(쪽, 프로젝트)] = {'types': 그 프로젝트를 쓰는 서비스들의 tag 타입, 'roles': 배포 역할} — 남의 tag·배포를 빼려고.
    """
    found: dict[str, dict] = {}
    for side in ("center", "repo"):
        ci = cis.get(side)
        if side not in api or not ci:
            continue
        kinds = {n: j["kind"] for n, j in (ci.get("jobs") or {}).items()}
        if not set(kinds.values()) & (BUILD_KINDS | DEPLOY_KINDS):
            continue  # 이미지 빌드·배포 job 이 없는 CI(빌드만·알림만)
        if side == "repo" and "direct" not in kinds.values():
            continue  # repo 는 빌드만 하고 center 로 넘김 → 버전은 center 에서
        project = api[side][0]
        url, token = _gitlab_of({"gitlab": side}, cfg)
        key = (side, project)
        if key not in cache:
            cache[key] = _memo("tags", fetch_tag_jobs, url, token, project, cfg.connect_timeout) if url and token else None
        if cache[key] is None:
            continue
        own_type = str(svc.get("tag_type") or svc.get("type") or "web")
        own_role = str(svc.get("deploy_role") or "").lower()
        claim = claims.get(key, {})
        found[side] = pick_versions(
            cache[key], kinds,
            skip_types=claim.get("types", set()) - {own_type},
            other_roles=claim.get("roles", set()) - {own_role},
        )
    if not found:
        return None
    out: dict[str, dict] = {"build": {}, "deploy": {}}
    for what in ("build", "deploy"):
        for env in {e for v in found.values() for e in v[what]}:
            # repo 가 바로 복사하는 환경은 빌드·배포 둘 다 repo 의 그 job(center 에 옛 이미지가 남아 있어도), 나머지는 center 먼저
            by_repo = (row["data"].get("deploy") or {}).get(env, {}).get("by") == "repo"
            for side in ("repo", "center") if by_repo else ("center", "repo"):
                if env in found.get(side, {}).get(what, {}):
                    out[what][env] = {**found[side][what][env], "side": side}
                    break
    return out


def _build_from_log(row: dict, ci: dict | None, project: str, cfg: RunnerConfig, cache: dict) -> str | None:
    """repo CI 에 런타임 이미지가 없을 때(shell 러너 — 서버에 깔린 node 로 빌드) 최근 성공한 build job 로그에서
    node·java 버전을 읽어 repo.build 에 붙인다. 반환: 그 job 이 돈 러너 이름(로그에 버전이 없는 다른 서비스가 나눠 쓰게)."""
    repo = row["data"].get("repo")
    if repo is None or repo.get("build") or not ci:
        return None
    url, token = _gitlab_of({"gitlab": "repo"}, cfg)
    if not url or not token:
        return None
    kinds = {n: j["kind"] for n, j in (ci.get("jobs") or {}).items()}
    if project not in cache:
        cache[project] = _memo("jobs", fetch_recent_jobs, url, token, project, cfg.connect_timeout) or []
    job = next(
        (j for j in cache[project] if j["status"] == "success" and kinds.get(j["name"]) == "other" and "build" in str(j["name"]).lower()),
        None,
    )
    if not job:
        return None
    found = parse_build_log_versions(
        _memo("log", fetch_job_log_head, url, token, project, job["id"], cfg.connect_timeout, max_bytes=200_000)
    )
    repo["build"] = [
        {"runtime": rt, "version": v, "image": None, "jobs": [job["name"]], "from": "log", "job": job["id"], "runner": job.get("runner_name")}
        for rt, v in found.items()
    ]
    return job.get("runner_name")


REPO_SIDE_KEYS = ("repo", "executor_repo", "deploy", "env_keys")  # repo CI(repo GitLab)로 정해지는 칸


def _keep_repo_side(row: dict, prev: dict | None) -> None:
    """repo GitLab 에 접속이 안 된 수집 — repo CI 로 정해지는 칸(repo 빌드·코드 버전 · repo executor · 배포 경로)은
    비우지 않고 지난 수집 값을 이어 씀. 빌드·배포 버전은 이번에 center 에서 읽은 것을 쓰되, repo 가 서버로 바로
    복사하는 환경(지난 배포 경로 by=repo)과 center 에 없는 환경은 지난 repo 값. 이어 쓴 값에는 kept 표시."""
    row["env_hash"] = None  # repo variables 를 못 봄 → '바뀜' 판단 안 함
    if not prev:
        return
    data = row["data"]
    for k in REPO_SIDE_KEYS:
        if k in prev:
            data[k] = prev[k]
    if isinstance(data.get("repo"), dict) and not data["repo"].get("missing"):
        data["repo"] = {**data["repo"], "kept": True}
    pv = prev.get("versions") or {}
    cur = data.get("versions") or {"build": {}, "deploy": {}}
    for what in ("build", "deploy"):
        for env, v in (pv.get(what) or {}).items():
            by_repo = ((data.get("deploy") or {}).get(env) or {}).get("by") == "repo"
            if v.get("side") == "repo" and (by_repo or env not in cur.setdefault(what, {})):
                cur.setdefault(what, {})[env] = {**v, "kept": True}
    if any(cur.get(w) for w in ("build", "deploy")):
        data["versions"] = cur


def _load_prev(cfg: RunnerConfig) -> tuple[dict[str, dict], dict[str, dict]]:
    """지난 수집(비교표 서비스 → 줄, config 줄 → 줄) — 이번에 못 읽은 칸을 이어 쓰려고."""
    api_prev = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        return {str(r["service"]): r for r in api_prev.list_shapes()}, {str(r["path"]): r for r in api_prev.list_config()}
    finally:
        api_prev.close()


def _prefetch(services: list[dict], cdirs: list[str], config_files: Any, cfg: RunnerConfig, source: str, base_dir: str) -> None:
    """미리 읽기 — 아래에서 서비스마다 하나씩 부를 GitLab 호출을 GITLAB_WORKERS 개씩 동시에 먼저 불러 둔다(_MEMO 에).
    CI 파일 · repo 버전 파일 · config 폴더 Dockerfile · 프로젝트마다 최근 job 목록 · center 의 tag 로 돈 job.
    서버 compose(SSH)는 여기서 안 함. 하나가 실패해도 괜찮음 — 아래에서 그때 다시 부름."""
    if _MEMO is None:
        return

    def ci_and_code(s: dict) -> None:
        for side in ("repo", "center"):
            src, api_side = _ci_source(s, side, cfg, source)
            if api_side:
                _read_source(src, cfg, base_dir)
                if side == "repo":
                    _code_files(src, cfg, base_dir)

    tasks: list[Any] = [lambda s=s: ci_and_code(s) for s in services]
    tasks += [lambda d=d: config_files(d) for d in cdirs]
    projects = {(side, p) for s in services for side in ("repo", "center") if (p := _project_of(s.get(side))[0]) and _use_api(p, source)}
    for side, project in sorted(projects):
        url, token = _gitlab_of({"gitlab": side}, cfg)
        if not url or not token:
            continue
        tasks.append(lambda u=url, t=token, p=project: _memo("jobs", fetch_recent_jobs, u, t, p, cfg.connect_timeout))
        if side == "center":
            tasks.append(lambda u=url, t=token, p=project: _memo("tags", fetch_tag_jobs, u, t, p, cfg.connect_timeout))
    with ThreadPoolExecutor(max_workers=GITLAB_WORKERS) as pool:
        for f in [pool.submit(t) for t in tasks]:
            try:
                f.result()
            except Exception:  # 미리 읽기 실패는 무시 — 본 수집에서 다시 부름
                pass


def _config_listing(config: dict, cfg: RunnerConfig, base_dir: str):
    """config 섹션 → ({'<서비스>/<타입>': [파일 이름…]}, read('<서비스>/<타입>/<파일>')) 또는 None."""
    if config.get("file"):
        root = os.path.join(base_dir, os.path.expanduser(str(config["file"])))
        if not os.path.isdir(root):
            return None
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            rel = os.path.relpath(dirpath, root)
            if rel != "." and rel.count(os.sep) <= 1:  # <서비스>/<타입> 또는 <서비스>(Dockerfile 을 바로 둔 곳)
                paths += [f"{rel.replace(os.sep, '/')}/{n}" for n in filenames]

        def read_local(rel: str) -> str | None:
            try:
                with open(os.path.join(root, rel), encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return None

        return config_dirs(paths), read_local
    url, token = _gitlab_of(config, cfg)
    if not url or not token or not config.get("project"):
        return None
    ref = str(config.get("ref") or cfg.gitlab_ref or "")  # 비우면 프로젝트 기본 브랜치
    tree = _memo("tree", fetch_repo_tree, url, token, str(config["project"]), ref, cfg.connect_timeout)
    if tree is None:
        return None
    return config_dirs(tree), lambda rel: _memo("file", fetch_repo_file, url, token, str(config["project"]), rel, ref, cfg.connect_timeout)


def _ssh_src(src: object) -> bool:
    """서버에 SSH 로 들어가 읽는 소스인가({ssh: …})."""
    return isinstance(src, dict) and bool(src.get("ssh"))


def cmd_shape(
    cfg: RunnerConfig, targets_path: str | None = None, ssh_mode: str | None = None, source: str = "api", no_ssh: bool = False,
) -> dict:
    """비교표 + config 수집 한 번. 이 동안만 GitLab 호출을 기억(_MEMO)하고, 미리 읽기는 동시에 → 끝나면 비움."""
    global _MEMO
    _MEMO = {}
    reset_down()
    started = time.monotonic()
    try:
        res = _shape(cfg, targets_path, ssh_mode, source, no_ssh)
    finally:
        _MEMO = None
        reset_down()
    secs = round(time.monotonic() - started)
    print(f"걸린 시간: {secs}초")
    if res.get("ok"):
        res = {**res, "message": f"{res['message']} · {secs}초"}
    return res


def _shape(
    cfg: RunnerConfig, targets_path: str | None = None, ssh_mode: str | None = None, source: str = "api", no_ssh: bool = False,
) -> dict:
    """ssh_mode: None = 대상 파일에 적힌 것만 / 'plan' = center CI 로 서버 compose 위치를 찾아 목록만 출력(접속 안 함)
    / 'read' = 그 목록대로 SSH 로 실제 읽음(대상 파일에 이미 적힌 환경은 건드리지 않음).
    source: GitLab 파일을 어디서 읽나 — api(기본: 무조건 GitLab, 토큰 없으면 멈춤) / local(로컬 사본, 고를 때만).
    no_ssh: GitLab 만 다시 읽음(SSH 키 없는 서버의 수집기) — 서버 compose 는 지난 수집 값을 이어 씀.
    반환: {ok, message} — 수집기가 화면 요청을 '완료/실패'로 닫을 때 씀."""
    if no_ssh:
        ssh_mode = None
    path = targets_path or cfg.shape_targets
    if not os.path.exists(path):
        print(f"비교표 대상 파일 없음({path}) — runner/shape-targets.example.yml 을 복사해 채우세요.")
        return {"ok": False, "message": f"대상 파일 없음({os.path.basename(path)})"}
    with open(path, encoding="utf-8") as f:
        targets_text = f.read()
    runners, services, configs = parse_targets(targets_text)
    gateways, gateway_user = parse_gateways(targets_text)
    gateway_sudo = parse_gateway_sudo(targets_text)  # 이 gw 들은 root 의 ssh 설정으로(sudo -n)
    if not services and not configs:
        print(f"비교표 대상이 비어 있음 — {path} 의 services: / config: 를 채우세요.")
        return {"ok": False, "message": "대상 파일이 비어 있음"}
    base_dir = os.path.dirname(os.path.abspath(path))
    # config repo 들도 project: 가 있으면 API 로(--source local 일 때만 file:)
    cfg_api_sides: set[str] = set()
    for i, c in enumerate(configs):
        cproj, cref = _project_of(c.get("project"))
        cside = str(c.get("gitlab") or "center")
        if _use_api(cproj, source):
            configs[i] = {k: v for k, v in c.items() if k != "file"} | {"gitlab": cside, "project": cproj, **({"ref": cref} if cref else {})}
            cfg_api_sides.add(cside)
    config_api = bool(cfg_api_sides)
    api_sides = {side for side in ("repo", "center") if any(_use_api(_project_of(s.get(side))[0], source) for s in services)}
    print(
        "읽는 곳: "
        + " · ".join(f"{side} {'GitLab API' if side in api_sides else '로컬 사본'}" for side in ("repo", "center"))
        + f" · config {'GitLab API' if config_api else '로컬 사본'}"
        + (" (--source local)" if source == "local" else "")
    )
    # 기본은 무조건 GitLab — 토큰이 없으면 빈 표를 올리지 않고 멈춤
    no_token = sorted({*api_sides, *cfg_api_sides} - {s for s in ("repo", "center") if _api_ready(s, cfg)})
    if no_token:
        env = {"repo": "CT_GITLAB_URL·CT_GITLAB_TOKEN", "center": "CT_GITLAB_CENTER_URL·CT_GITLAB_CENTER_TOKEN"}
        print(
            f"  GitLab 토큰이 없어 멈춤({'·'.join(no_token)}) — .env 에 {' / '.join(env[s] for s in no_token)}(read_api) 를 넣거나,"
            " 로컬 사본으로 보려면 --source local"
        )
        return {"ok": False, "message": f"GitLab 토큰이 없어 멈춤({'·'.join(no_token)})"}
    if source != "local":  # 프로젝트 이름이 없어 로컬 사본을 읽는 서비스(알려만 줌)
        local_only = [
            f"{s['name']}({'·'.join(side for side in ('repo', 'center') if not _project_of(s.get(side))[0] and s.get(f'{side}_ci'))})"
            for s in services
            if any(not _project_of(s.get(side))[0] and s.get(f"{side}_ci") for side in ("repo", "center"))
        ]
        if local_only:
            print(f"  프로젝트 이름이 없어 로컬 사본을 읽음: {', '.join(local_only)} — repo:/center: 를 적으면 GitLab 으로")
    prev_shapes: dict[str, dict] = {}  # GitLab 만 읽을 때 — 서비스 → 지난 수집(서버 compose 판독 결과를 이어 씀)
    prev_config: dict[str, dict] = {}  # config 줄 → 지난 수집
    if no_ssh:
        print("  서버 compose 는 SSH 로 안 읽음(GitLab 만) — 지난 수집 값을 이어 씀")
        prev_shapes, prev_config = _load_prev(cfg)
    # config repo 들의 폴더를 한 표로 모음 — 폴더마다 어느 repo 에서 읽나(reader)·그 repo 의 group
    dirs: dict[str, list[str]] = {}
    readers: dict[str, Any] = {}
    dir_group: dict[str, str] = {}
    dir_repo: dict[str, str] = {}  # 폴더 → 어느 config repo 에서 왔나(GitLab 프로젝트, 없으면 로컬 경로)
    merged_map: dict[str, str] = {}
    compose_map: dict[str, dict] = {}
    for c in configs:
        listing = _config_listing(c, cfg, base_dir)
        if listing is None:
            print(f"  config 를 읽지 못함({c.get('project') or c.get('file')}) — file 경로 또는 GitLab 설정을 확인하세요.")
            continue
        found, reader = listing
        for k, names in found.items():
            if k in dirs:  # 다른 config repo 에 같은 폴더 이름 — 먼저 적은 쪽
                print(f"  config 폴더 이름이 겹침: {k} — 먼저 적은 config repo 것을 씀")
                continue
            dirs[k], readers[k] = names, reader
            dir_repo[k] = str(c.get("project") or c.get("file") or "")
            if c.get("group"):
                dir_group[k] = str(c["group"])
        merged_map.update({str(k): str(v) for k, v in (c.get("merged") or {}).items()})
        compose_map.update(c.get("compose") or {})
    # Dockerfile·start.sh 가 없는 폴더(문서·템플릿 등)는 건너뜀 — 합쳐짐(merged)·서비스가 연결한 폴더는 남김
    keep = set(merged_map) | {str(sv["config_dir"]) for sv in services if sv.get("config_dir")}
    skipped = [
        k for k, names in dirs.items()
        if k not in keep and not any(is_dockerfile(n) or re.search(r"start[\w-]*\.sh", n, re.I) for n in names)
    ]
    for k in skipped:
        dirs.pop(k)
    if skipped:
        print(f"  config 폴더 건너뜀(Dockerfile·start.sh 없음): {', '.join(sorted(skipped))}")

    def config_files(cdir: str) -> tuple[str | None, str | None]:
        """config 폴더의 (Dockerfile 원문, start.sh 이름|None)."""
        names = dirs.get(cdir, [])
        df = next((n for n in names if is_dockerfile(n)), None)
        sh = next((n for n in names if re.search(r"start[\w-]*\.sh", n, re.I)), None)
        reader = readers.get(cdir)
        return (reader(f"{cdir}/{df}") if (df and reader) else None), sh

    _prefetch(services, list(dirs), config_files, cfg, source, base_dir)
    if "repo" in api_sides and is_down(cfg.gitlab_url):
        print("  repo GitLab 에 접속이 안 됨 — 기다리지 않고 건너뜀, repo 쪽 칸은 지난 수집 값을 이어 씀")
        if not no_ssh:
            prev_shapes, prev_config = _load_prev(cfg)
    rows, missing = [], []
    compose_by_dir: dict[str, dict[str, str | None]] = {}
    src_by_dir: dict[str, dict[str, dict]] = {}  # config 폴더 → 환경 → 어디서 읽었나
    miss_by_dir: dict[str, dict[str, dict]] = {}  # config 폴더 → 환경 → 못 읽음(이유) / 위치만 찾음
    envs_by_dir: dict[str, set[str]] = {}  # config 폴더 → 그 서비스가 배포하는 환경(비교표 기준)
    # 폴더 하나를 폴더 이름과 다른 타입(역할)으로 쓰면 → 역할마다 한 줄 '<서비스>/<역할>' (예: web 폴더 이미지를 manager·syncer 가)
    roles_by_dir: dict[str, list[str]] = {}
    group_by_key: dict[str, str] = {}  # config 줄 → 그룹(연결된 서비스의 group)
    for s in services:
        c, t = s.get("config_dir"), str(s.get("type") or "web")
        if c and "/" in str(c) and t != str(c).partition("/")[2]:  # 타입 폴더 없이 바로 둔 곳(예: bot/Dockerfile)은 그대로
            roles_by_dir.setdefault(str(c), []).append(t)

    def row_key(s: dict) -> str | None:
        """config 표의 줄 이름 — 보통은 폴더, 역할로 나뉘면 '<서비스>/<역할>'."""
        c = s.get("config_dir")
        if c and str(c) in roles_by_dir:
            return f"{str(c).partition('/')[0]}/{s.get('type') or 'web'}"
        return c

    def miss(cdir: str | None, env: str, state: str, reason: str) -> None:
        """화면에 '안 읽음'(시도 안 함)과 구분해서 보여줄 것: fail = 읽으려다 실패, planned = 위치만 찾음."""
        if cdir:
            miss_by_dir.setdefault(cdir, {}).setdefault(env, {"state": state, "reason": reason})
    plan: list[tuple[str, str, str | None, str, str, str | None]] = []  # (서비스, 환경, ssh 별칭|None, 주소, 경로, 경유 gw|None)
    by_ip: dict[str, str] = {}
    gw_names: dict[str, dict[str, str]] = {}  # gw → {안쪽 서버 주소: gw 에 등록된 이름} (읽기 모드에서 gw 마다 한 번)
    if ssh_mode:
        api0 = CentralAPI(cfg.central_url, cfg.api_token)
        try:  # 서버 주소 → ~/.ssh/config 별칭(러너가 접속할 이름)
            by_ip = {str(x.get("ip")): x["hostname"] for x in api0.list_servers() if x.get("ip")}
        finally:
            api0.close()
    code_by_dir: dict[str, dict] = {}  # config 폴더 ↔ 코드에 적힌 버전(서비스의 repo CI 옆 파일들)
    for cdir, envs in compose_map.items():
        for env, src in ((e, _pick(x, source)) for e, x in (envs or {}).items()):
            if no_ssh and _ssh_src(src):
                continue  # 지난 수집 값을 이어 씀(아래 config 줄 만들 때)
            tried, text = _read_source(src, cfg, base_dir)
            if tried and text is None:
                missing.append(f"config {cdir}:compose.{env}")
                miss(str(cdir), str(env), "fail", "적어 둔 파일을 못 읽음(없음·권한·접속 실패)")
            compose_by_dir.setdefault(str(cdir), {})[str(env)] = text
            if text:
                src_by_dir.setdefault(str(cdir), {})[str(env)] = _src_info(src)
    log_cache: dict = {}  # (repo|center, runner id) → job 로그로 본 executor (같은 러너는 한 번만)
    tag_cache: dict = {}  # (repo|center, 프로젝트) → tag 로 돈 성공 job (같은 프로젝트는 한 번만)
    build_jobs: dict = {}  # repo 프로젝트 → 최근 job (shell 빌드의 로그 읽기용)
    runner_seen: dict[str, dict[str, dict]] = {}  # 러너 이름 → {런타임: 로그에서 본 빌드 버전}
    log_pending: list[tuple[dict, str]] = []  # 로그에 버전 줄이 없던 서비스 → 같은 러너 값으로 채움(추정)
    claims: dict[tuple[str, str], dict[str, set[str]]] = {}  # 같은 프로젝트를 쓰는 서비스들의 tag 타입·배포 역할
    for s in services:
        for side in ("repo", "center"):
            proj = _project_of(s.get(side))[0]
            if proj:
                c = claims.setdefault((side, proj), {"types": set(), "roles": set()})
                c["types"].add(str(s.get("tag_type") or s.get("type") or "web"))
                if s.get("deploy_role"):
                    c["roles"].add(str(s["deploy_role"]).lower())
    for svc in services:
        files: dict = {}
        api: dict[str, tuple[str, str | None]] = {}  # API 로 읽은 쪽 → (프로젝트, ref)
        repo_src, api_repo = _ci_source(svc, "repo", cfg, source)
        center_src, api_center = _ci_source(svc, "center", cfg, source)
        api.update({k: v for k, v in (("repo", api_repo), ("center", api_center)) if v})
        srcs = {"repo_ci": repo_src, "center_ci": center_src, "dockerfile": _pick(svc.get("dockerfile"), source), "startup": _pick(svc.get("startup"), source)}
        for key in ("repo_ci", "center_ci", "dockerfile", "startup"):
            tried, text = _read_source(srcs[key], cfg, base_dir)
            if tried:
                files[key] = text
                if text is None and key != "startup":  # start.sh 는 '없음'이 정상 결과
                    missing.append(f"{svc['name']}:{key}")
        cdir = svc.get("config_dir")
        ckey = row_key(svc)  # config 표의 줄(보통 = 폴더)
        if cdir and cdir in dirs:  # dockerfile/startup 을 config 폴더에서 채움
            df_text, sh = config_files(cdir)
            files.setdefault("dockerfile", df_text)
            files.setdefault("startup", sh)
        compose = {}
        for env, src in ((e, _pick(x, source)) for e, x in (svc.get("compose") or {}).items()):
            if no_ssh and _ssh_src(src):
                continue
            tried, text = _read_source(src, cfg, base_dir)
            if tried and text is None:
                missing.append(f"{svc['name']}:compose.{env}")
                miss(ckey, str(env), "fail", "적어 둔 파일을 못 읽음(없음·권한·접속 실패)")
            compose[str(env)] = text
            if ckey and text:
                compose_by_dir.setdefault(ckey, {}).setdefault(str(env), text)
                src_by_dir.setdefault(ckey, {}).setdefault(str(env), _src_info(src, svc.get("source_note")))
        # center CI 에 적힌 배포 서버·폴더로 나머지 환경의 서버 compose 를 찾는다
        if ssh_mode and files.get("center_ci"):
            role = str(svc["deploy_role"]).lower() if svc.get("deploy_role") else None  # 예: mgr / wrk
            for env, t in deploy_targets(files["center_ci"], str(svc.get("tag_type") or svc.get("type") or "web"), role).items():
                if env in compose or not t["dir"]:
                    continue
                ip = t["hosts"][0]
                alias = by_ip.get(ip)
                via = None if alias else gateways.get(env)  # 직접 등록 안 된 서버면 그 환경의 gw 를 거침
                path_ = f"{t['dir']}/docker-compose.yml"
                plan.append((str(svc["name"]), env, alias, ip, path_, via))
                if ssh_mode != "read":
                    where = f"{alias}" if alias else (f"{via} → {ip}" if via else "(SSH 설정에 없는 서버)")
                    miss(ckey, env, "planned", f"위치는 찾음: {where}:{path_} — --ssh 로 읽기")
                    continue
                if not alias and not via:
                    miss(ckey, env, "fail", f"~/.ssh/config 에 직접 등록 안 된 서버 — 게이트웨이를 거쳐야 할 수 있음(gateways: 에 이 환경의 gw 를 적으면 경유) — {path_}")
                    continue
                if alias:
                    src = {"ssh": alias, "path": path_}
                    _, text = _read_source(src, cfg, base_dir)
                    fail_where = f"{alias}:{path_}"
                else:
                    # gw 에 이름으로 등록된 서버면 그 이름으로(gw 의 계정·키·지문 설정을 그대로) — 없으면 주소로
                    sudo = via in gateway_sudo
                    if via not in gw_names:
                        gw_names[via] = gateway_aliases(via, cfg.connect_timeout, sudo)
                    inner = gw_names[via].get(ip)
                    src = {"ssh": inner or ip, "via": via, "path": path_, "sudo": sudo}
                    text, err = read_file_via(via, inner or ip, path_, cfg.connect_timeout, None if inner else gateway_user, sudo)
                    who = "gw 의 root" if sudo else "gw 로그인 계정의"
                    hint = "" if inner else f" · {who} ssh 설정에 이 서버 이름이 없음(등록하면 그 설정으로 접속)"
                    fail_where = f"{via} → {inner or ip}:{path_} ({err}){hint}"
                if text is None:
                    missing.append(f"{svc['name']}:compose.{env}(ssh {alias or via})")
                    miss(ckey, env, "fail", f"SSH 로 못 읽음(접속·권한·파일 없음) — {fail_where}")
                    continue
                compose[env] = text
                if ckey:
                    compose_by_dir.setdefault(ckey, {}).setdefault(env, text)
                    src_by_dir.setdefault(ckey, {}).setdefault(env, _src_info(src, auto=True))
        files["compose"] = compose
        if no_ssh:  # 이번에 안 읽은 환경 → 지난 수집의 compose 판독 결과
            kept = (prev_shapes.get(str(svc["name"])) or {}).get("compose_facts") or {}
            files["compose_facts"] = {e: f for e, f in kept.items() if not compose.get(e)}
        row = build_row(svc, files, runners)
        for side, (project, _ref) in api.items():  # API 로 읽은 쪽은 job 로그로 executor 확정
            k = f"executor_{side}"
            row["data"][k] = confirm_executor(row["data"].get(k), _executor_from_logs(side, project, row["data"].get(k), cfg, log_cache))
        cis = {"repo": analyze_ci(files.get("repo_ci")), "center": analyze_ci(files.get("center_ci"))}
        if "repo" in api:  # shell 빌드(이미지 없음) → build job 로그에서 버전
            runner = _build_from_log(row, cis["repo"], api["repo"][0], cfg, build_jobs)
            if runner:
                for b in row["data"]["repo"]["build"]:
                    runner_seen.setdefault(runner, {}).setdefault(b["runtime"], b)
                if not row["data"]["repo"]["build"]:
                    log_pending.append((row, runner))
        versions = _versions_of(svc, row, cis, api, claims, cfg, tag_cache)
        if versions is not None:  # 없으면 화면에서 '모름'(API 로 안 읽음)
            row["data"]["versions"] = versions
        if ckey:
            envs_by_dir.setdefault(ckey, set()).update(row["data"]["deploy"])
            if svc.get("group"):
                group_by_key.setdefault(ckey, str(svc["group"]))
        if repo_src:  # 코드에 적힌 버전 — repo 탭(서비스마다) + center 탭(config 폴더마다)
            code_files = _code_files(repo_src, cfg, base_dir)
            cv = code_versions(code_files)
            if row["data"].get("repo") is not None:
                row["data"]["repo"]["code"] = cv
            if ckey and cv:
                code_by_dir.setdefault(ckey, cv)
        if cdir and cdir in dirs:  # start.sh 칸 색: config 폴더 기준(실행에 씀 / 파일만 남음 / 없음)
            row["data"]["start_state"] = analyze_config_dir(dirs[cdir], config_files(cdir)[0])["state"]
        if "repo" in api and is_down(cfg.gitlab_url):  # repo GitLab 에 접속 안 됨 → repo 쪽 칸은 지난 값
            _keep_repo_side(row, prev_shapes.get(str(svc["name"])))
        rows.append(row)

    for row, runner in log_pending:  # 같은 러너(같은 서버)에서 빌드 → 그 서버의 node 를 쓴다고 보고 추정으로
        seen = runner_seen.get(runner, {}).get(str(row["data"].get("runtime")))
        if seen:
            row["data"]["repo"]["build"] = [{**seen, "guess": True}]
    items = []
    # 서비스와 연결 안 된 폴더의 그룹: 그 config repo 의 group, 없으면 연결된 서비스들의 가장 많은 그룹
    default_group = (Counter(group_by_key.values()).most_common(1) or [(None, 0)])[0][0]
    for cdir in sorted(dirs):
        df_text, _ = config_files(cdir)
        svc_name = cdir.partition("/")[0]
        keys = [f"{svc_name}/{r}" for r in dict.fromkeys(roles_by_dir[cdir])] if cdir in roles_by_dir else [cdir]
        for key in keys:  # 보통 폴더 하나 = 한 줄, 역할로 나뉘면 역할마다 한 줄(같은 폴더)
            data = analyze_config_dir(dirs[cdir], df_text)
            moves = {env: (analyze_compose(t) or {}).get("start") for env, t in compose_by_dir.get(key, {}).items() if t}
            data["compose"] = {env: m for env, m in moves.items() if m}
            data["compose_src"] = {env: src_by_dir.get(key, {}).get(env) for env in data["compose"]}  # 칸마다 어디서 읽었나
            data["compose_miss"] = {e: m for e, m in miss_by_dir.get(key, {}).items() if e not in data["compose"]}
            prev = prev_config.get(key) if no_ssh else None
            if prev:  # GitLab 만 읽었음 → 서버 compose 칸은 지난 수집 값(어디서 읽었나에 '지난 값' 표시)
                for env, start in (prev.get("compose") or {}).items():
                    if env not in data["compose"]:
                        data["compose"][env] = start
                        data["compose_src"][env] = {**((prev.get("compose_src") or {}).get(env) or {"kind": "unknown"}), "kept": True}
                        data["compose_miss"].pop(env, None)
                for env, m in (prev.get("compose_miss") or {}).items():
                    if env not in data["compose"]:
                        data["compose_miss"].setdefault(env, m)
            if envs_by_dir.get(key):  # 여기 없는 환경엔 배포를 안 함 → 화면에서 '안 읽음' 대신 '—' (CI 를 못 읽어 비면 안 붙임 = 모름)
                data["deploy_envs"] = sorted(envs_by_dir[key])
            if key != cdir:  # 역할 줄 — 실제 config 폴더
                data["folder"] = cdir
            merged = merged_map.get(cdir)
            if merged:  # 다른 폴더로 합쳐져 안 쓰는 폴더(예: repo 둘이 center 에서 하나로)
                data["merged_into"] = str(merged)
            data["code"] = code_by_dir.get(key)  # 코드에 적힌 버전(없으면 None)
            if data["code"] is None and is_down(cfg.gitlab_url):  # repo GitLab 에 접속 안 됨 → 지난 값
                data["code"] = (prev_config.get(key) or {}).get("code")
            data["group"] = group_by_key.get(key) or dir_group.get(cdir) or default_group
            if dir_repo.get(cdir):
                data["config_repo"] = dir_repo[cdir]  # 화면 그룹 칸에 '어느 config repo' 로
            items.append({"path": key, "data": data})

    # center(빌드·배포 버전 · config)에 접속이 안 되면 올리지 않음 — 올리면 표가 비어 버림
    dead = sorted(s for s in (api_sides & {"center"}) | cfg_api_sides if is_down(_gitlab_of({"gitlab": s}, cfg)[0]))
    if dead:
        print(f"  {'·'.join(dead)} GitLab 에 접속이 안 됨 — 표를 덮어쓰지 않고 멈춤(지난 값 그대로)")
        return {"ok": False, "message": f"{'·'.join(dead)} GitLab 접속 안 됨 — 표는 지난 값 그대로"}
    repo_down = "repo" in api_sides and is_down(cfg.gitlab_url)
    if repo_down:  # 서비스마다 '못 읽은 파일'로 늘어놓는 대신 한 줄로
        missing = [m for m in missing if not m.endswith(":repo_ci")]
    summary: list[str] = []
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        if services:
            res = api.upload_shapes(rows, replace=True)  # 대상 파일이 기준 — 빠진 서비스는 표에서 내림
            print(f"비교표 수집: {res['accepted']}개 서비스")
            summary.append(f"서비스 {res['accepted']}개")
            with_ver = sum(1 for r in rows if r["data"].get("versions"))
            from_log = [b for r in rows for b in ((r["data"].get("repo") or {}).get("build") or []) if b.get("from") == "log"]
            if from_log:
                print(f"  repo 빌드 버전(job 로그): {len(from_log)}개 (같은 러너로 추정 {sum(1 for b in from_log if b.get('guess'))})")
            print(f"  빌드·배포 버전: {with_ver}개 서비스 (tag 로 돈 job · 프로젝트 {sum(1 for v in tag_cache.values() if v is not None)}개)")
        if configs:
            res = api.upload_config(items, replace=True)
            print(f"config 수집: {res['accepted']}개 줄")  # 보통 폴더 하나 = 한 줄(역할로 나뉘면 역할마다)
            summary.append(f"config {res['accepted']}줄")
    finally:
        api.close()
    if plan:
        direct = sum(1 for p in plan if p[2])
        via_n = sum(1 for p in plan if not p[2] and p[5])
        print(f"서버 compose 자동 찾기: {len(plan)}곳 (직접 {direct} · gw 경유 {via_n} · 길 없음 {len(plan) - direct - via_n})")
        for name, env, alias, ip, path_, via in plan:
            if alias:
                where = f"{alias}:{path_}"
            elif via:
                where = f"{via} → {ip}:{path_}"
            else:
                where = f"(직접 등록 안 된 서버 {ip}, gateways: 에 gw 없음) {path_}"
            print(f"  {name:22} {env:8} → {where}")
        if ssh_mode == "plan":
            print("  ※ 목록만 보여줬어요(접속 안 함). 실제로 읽으려면: python -m runner.cli shape --ssh")
    if missing:
        print(f"  못 읽은 파일 {len(missing)}개: {', '.join(missing)}")
        summary.append(f"못 읽은 파일 {len(missing)}개")
    if repo_down:
        summary.append("repo GitLab 접속 안 됨 · repo 쪽은 지난 값")
    if no_ssh:
        summary.append("서버 compose 는 지난 값")
    return {"ok": True, "message": " · ".join(summary)}


def _daily_since(now: datetime, at: str, tz: str) -> str | None:
    """오늘(tz 기준)의 자동 수집 시각이 지났으면 그 시각(ISO, UTC), 아직이면 None. at = 'HH:MM'."""
    local = now.astimezone(ZoneInfo(tz))
    hh, mm = (int(x) for x in at.split(":"))
    due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return due.astimezone(timezone.utc).isoformat(timespec="seconds") if local >= due else None


STATUS_RESEND_SECONDS = 60  # 서버 상태가 그대로여도 이만큼마다 다시 올림


def cmd_agent(
    cfg: RunnerConfig, targets_path: str | None = None, interval: float = 5.0, once: bool = False, ssh: bool = False,
    name: str | None = None, daily_at: str | None = None, tz: str = "Asia/Seoul",
) -> None:
    """화면 [다시 수집] 요청(수동)과 매일 정해 둔 시각(자동)에 수집하는 수집기 — ControlTower 와 같은 서버(또는 PC)에 켜 둔다.

    interval 초마다 ControlTower 에 요청이 있는지 확인(켜져 있다는 표시도 됨) → 있으면 shape 수집 → 완료/실패로 닫음.
    daily_at('09:00', tz 기준)이 지나면 하루 한 번 자동 요청 — 그 뒤로 끝난 수집(버튼 포함)이 있으면 건너뜀.
    수집기가 그 시각에 꺼져 있었으면 켜질 때 한 번 돈다(판단은 중앙 DB 로 해서 다시 켜도 두 번 안 돎).
    기본은 GitLab 만 다시 읽음(서버에 SSH 키 없이). ssh=True 면 서버 compose 도 SSH 로(키가 있는 PC 에서만).
    """
    name = name or cfg.runner_name
    mode = "gitlab+ssh" if ssh else "gitlab"
    schedule = f"{daily_at} {tz}" if daily_at else None
    status_file = (getattr(cfg, "idp_status_file", "") or "").strip()  # 빈 값이면 서버 상태 읽기를 끔
    print(
        f"수집기 시작: {name} ({mode}) — {interval:g}초마다 요청 확인" + (f" · 자동 매일 {schedule}" if schedule else " · 자동 없음(버튼만)")
        + (f" · 서버 상태 파일 {status_file}" if status_file else " · 서버 상태 읽기 꺼짐")
    )
    asked: str | None = None  # 오늘 자동 요청을 이미 물어봤나(같은 날 반복 호출 줄이기)
    sent: tuple | None = None  # 서버 상태 — 마지막으로 올린 (읽음?, 이유, 기록 시각)
    sent_at, sent_summary, sent_error = 0.0, "", ""
    while True:
        api = CentralAPI(cfg.central_url, cfg.api_token)
        try:
            if status_file:  # 서버 상태 파일 — 바뀌었으면 바로, 아니어도 1분마다(중앙이 '수집기가 살아 있음' 을 알게)
                snap = read_status(status_file)
                key = (snap["read_ok"], snap.get("read_error"), snap.get("written_at"))
                if key != sent or time.monotonic() - sent_at >= STATUS_RESEND_SECONDS:
                    try:  # 올리기 실패가 수집 요청 확인까지 막지 않게 따로
                        api.upload_host_status("idp", name, snap)
                    except httpx.HTTPError as e:
                        if str(e) != sent_error:
                            print(f"[{time.strftime('%H:%M:%S')}] 서버 상태를 못 올림: {e}")
                        sent_error = str(e)
                    else:
                        if summary(snap) != sent_summary:  # 로그는 상태가 바뀔 때만
                            print(f"[{time.strftime('%H:%M:%S')}] 서버 상태: {summary(snap)}")
                        sent, sent_at, sent_summary, sent_error = key, time.monotonic(), summary(snap), ""
            since = _daily_since(datetime.now(timezone.utc), daily_at, tz) if daily_at else None
            if since and since != asked:
                res = api.request_auto("shape", since)
                asked = since
                if res.get("created"):
                    print(f"[{time.strftime('%H:%M:%S')}] 자동 수집 요청(매일 {schedule})")
            req = api.claim_collect("shape", name, mode, schedule)
            if req:
                print(f"[{time.strftime('%H:%M:%S')}] 요청 #{req['id']} 수집 시작")
                try:
                    res = cmd_shape(cfg, targets_path, "read" if ssh else None, no_ssh=not ssh)
                except Exception as e:  # 수집 중 오류 → 실패로 닫고 계속 기다림
                    res = {"ok": False, "message": f"수집 중 오류: {type(e).__name__}: {e}"[:300]}
                api.finish_collect(req["id"], res["ok"], res["message"])
                print(f"[{time.strftime('%H:%M:%S')}] 요청 #{req['id']} {'완료' if res['ok'] else '실패'} — {res['message']}")
        except httpx.HTTPError as e:
            print(f"[{time.strftime('%H:%M:%S')}] ControlTower 에 못 닿음: {e}")
        finally:
            api.close()
        if once:
            return
        time.sleep(interval)


def cmd_apply(cfg: RunnerConfig, dry_run: bool = False, rollback_id: int | None = None) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        if rollback_id is not None:
            it = next((x for x in api.list_apply_intents() if x["id"] == rollback_id), None)
            if it is None:
                print(f"의도 {rollback_id} 를 찾을 수 없습니다.")
                return
            if not it.get("backup_path"):
                print("백업 경로가 없어 롤백할 수 없습니다.")
                return
            res = applier.rollback(it["hostname"], it["path"], it["backup_path"], sudo=cfg.apply_sudo, timeout=cfg.connect_timeout)
            if res["ok"]:
                api.post_apply_rollback(rollback_id)
                print(f"롤백 완료: {it['hostname']}:{it['path']} ← {it['backup_path']}")
            else:
                print(f"롤백 실패: {res['error']}")
            return

        intents = api.list_apply_intents(status="approved")
        if not intents:
            print("승인된 적용 대상이 없습니다.")
            return
        for it in intents:
            c = api.get_apply_content(it["id"])  # {path, content, to_sha} — 승인 후 기준본 변경 시 여기서 409
            if dry_run:
                print(f"[dry-run] {it['hostname']}:{it['path']} → 기준본 적용 예정(백업 후 원자 교체)")
                continue
            res = applier.apply_intent(
                it["hostname"], c["path"], c["content"], c["to_sha"], sudo=cfg.apply_sudo, timeout=cfg.connect_timeout
            )
            if res["ok"]:
                api.post_apply_result(it["id"], "applied", backup_path=res["backup_path"])
                print(f"  ✓ {it['hostname']}:{it['path']} 적용됨 (백업 {res['backup_path']})")
            else:
                api.post_apply_result(it["id"], "failed", backup_path=res["backup_path"], error=res["error"])
                print(f"  ✗ {it['hostname']}:{it['path']} 실패: {res['error']}")
    finally:
        api.close()


def cmd_probe(cfg: RunnerConfig, group: str | None = None, host: str | None = None, online: bool = False) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = _select(api.list_servers(), group, host, online)
        if not servers:
            print("대상 서버가 없습니다(필터 확인).")
            return
        results = []
        for s in servers:
            p = probe_ssh(s["hostname"], cfg.connect_timeout)
            results.append({
                "server_id": s["id"],
                "ok": p["ok"],
                "needs_2fa": p["needs_2fa"],
                "error": None if p["ok"] else p["detail"],
            })
        ok_n = sum(1 for r in results if r["ok"])
        mfa_n = sum(1 for r in results if r["needs_2fa"])
        print(f"접속 점검: {ok_n}/{len(results)} 접속됨 · 추가인증(2FA) 추정 {mfa_n}")
        for s, r in zip(servers, results):
            if not r["ok"]:
                print(f"  · {s['hostname']}: {r['error']}")
        if results:
            api.post_connection_tests(results)
    finally:
        api.close()


def run_all_once(cfg: RunnerConfig) -> None:
    """모든 수집기를 1회 실행. 한 스텝이 실패해도 나머지는 계속(격리)."""
    steps = [
        ("import", cmd_import),
        ("test", cmd_test),
        ("conf", cmd_conf),
        ("updates", cmd_updates),
        ("versions", cmd_versions),
    ]
    if cfg.gitlab_url and cfg.gitlab_token:
        steps += [("versions-repo", cmd_versions_repo), ("cicd", cmd_cicd)]
    if os.path.exists(cfg.shape_targets):
        steps.append(("shape", cmd_shape))
    for name, fn in steps:
        try:
            fn(cfg)
        except Exception as e:  # noqa: BLE001 - 한 스텝 실패가 전체 주기를 막지 않게
            print(f"  ✗ {name} 실패: {e}")


def cmd_all(cfg: RunnerConfig, loop: bool = False, interval: int = 300) -> None:
    if not loop:
        run_all_once(cfg)
        return
    print(f"주기 수집 시작 — {interval}s 간격 (Ctrl-C 로 종료)")
    while True:
        run_all_once(cfg)
        time.sleep(interval)


def main() -> None:
    p = argparse.ArgumentParser(prog="ct-runner", description="Control Tower 러너")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="~/.ssh/config → 중앙 인벤토리 임포트")
    imp.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력(전송 안 함)")
    def _flt(pp):  # 대상 좁히기 필터(공통)
        pp.add_argument("--group", help="이 그룹만 대상")
        pp.add_argument("--host", help="이 호스트(별칭)만 대상")
        pp.add_argument("--online", action="store_true", help="접속된(online) 서버만 대상")
        return pp
    _flt(sub.add_parser("test", help="등록 서버 SSH 연결 테스트"))
    _flt(sub.add_parser("conf", help="관리 경로 conf 수집 → 드리프트 비교"))
    _flt(sub.add_parser("updates", help="서버별 대기 OS 패치(apt) 수집"))
    _flt(sub.add_parser("versions", help="빌드 서버 툴체인 버전(node/java/docker 등) 수집"))
    _flt(sub.add_parser("probe", help="접속 점검(접속 여부 + 2FA 추정)"))
    sub.add_parser("versions-repo", help="GitLab repo 선언본 버전 수집(CT_GITLAB_URL/TOKEN 필요)")
    sub.add_parser("cicd", help="GitLab 파이프라인 상태 수집(CT_GITLAB_URL/TOKEN 필요)")
    shp = sub.add_parser("shape", help="서비스 비교표 + center config 수집(shape-targets.yml — GitLab·로컬 파일·ssh)")
    shp.add_argument("--targets", help="대상 파일 경로(기본 CT_SHAPE_TARGETS 또는 ./shape-targets.yml)")
    g = shp.add_mutually_exclusive_group()
    g.add_argument("--ssh-plan", action="store_true", help="center CI 로 서버 compose 위치를 찾아 목록만 출력(접속 안 함)")
    g.add_argument("--ssh", action="store_true", help="그 목록대로 서버에 SSH 로 접속해 compose 를 읽음(읽기만)")
    shp.add_argument(
        "--source", choices=["api", "local"], default="api",
        help="GitLab 파일을 어디서 — api(기본): repo:/center:/project: 를 무조건 GitLab 으로(토큰 필요) / local: 로컬 사본",
    )
    agp = sub.add_parser("agent", help="화면 [다시 수집] 요청을 기다렸다 처리(ControlTower 와 같은 서버에 켜 둠)")
    agp.add_argument("--targets", help="대상 파일 경로(기본 CT_SHAPE_TARGETS 또는 ./shape-targets.yml)")
    agp.add_argument("--interval", type=float, default=5, help="요청 확인 간격(초, 기본 5)")
    agp.add_argument("--once", action="store_true", help="한 번만 확인하고 끝(cron·테스트용)")
    agp.add_argument("--ssh", action="store_true", help="서버 compose 도 SSH 로 읽음(키가 있는 PC 에서만) — 기본은 GitLab 만")
    agp.add_argument("--name", help="수집기 이름(기본 CT_RUNNER_NAME)")
    agp.add_argument(
        "--daily-at", default=os.environ.get("CT_COLLECT_DAILY_AT", ""),
        help="자동 수집 시각 HH:MM(기본 CT_COLLECT_DAILY_AT, 비우면 버튼만) — 예: 09:00",
    )
    agp.add_argument("--tz", default=os.environ.get("CT_COLLECT_TZ", "Asia/Seoul"), help="자동 수집 시각의 시간대(기본 Asia/Seoul)")
    allp = sub.add_parser("all", help="모든 수집기 1회 실행(--loop 로 주기 반복)")
    allp.add_argument("--loop", action="store_true", help="간격을 두고 반복 실행")
    allp.add_argument("--interval", type=int, default=300, help="반복 간격(초, 기본 300)")
    ap = sub.add_parser("apply", help="승인된 conf 를 서버에 실제 적용(백업·원자교체·verify)")
    ap.add_argument("--dry-run", action="store_true", help="쓰기 없이 적용 대상만 출력")
    ap.add_argument("--rollback", type=int, metavar="ID", help="해당 의도를 백업본으로 되돌림")
    args = p.parse_args()

    cfg = RunnerConfig.load()
    if args.cmd == "import":
        cmd_import(cfg, dry_run=args.dry_run)
    elif args.cmd == "test":
        cmd_test(cfg, args.group, args.host, args.online)
    elif args.cmd == "conf":
        cmd_conf(cfg, args.group, args.host, args.online)
    elif args.cmd == "updates":
        cmd_updates(cfg, args.group, args.host, args.online)
    elif args.cmd == "versions":
        cmd_versions(cfg, args.group, args.host, args.online)
    elif args.cmd == "probe":
        cmd_probe(cfg, args.group, args.host, args.online)
    elif args.cmd == "versions-repo":
        cmd_versions_repo(cfg)
    elif args.cmd == "cicd":
        cmd_cicd(cfg)
    elif args.cmd == "shape":
        cmd_shape(cfg, args.targets, "read" if args.ssh else ("plan" if args.ssh_plan else None), args.source)
    elif args.cmd == "agent":
        cmd_agent(
            cfg, args.targets, interval=args.interval, once=args.once, ssh=args.ssh, name=args.name,
            daily_at=args.daily_at or None, tz=args.tz,
        )
    elif args.cmd == "all":
        cmd_all(cfg, loop=args.loop, interval=args.interval)
    elif args.cmd == "apply":
        cmd_apply(cfg, dry_run=args.dry_run, rollback_id=args.rollback)


if __name__ == "__main__":
    main()
