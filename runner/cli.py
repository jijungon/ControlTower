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
import time

from . import applier
from .api import CentralAPI
from .apt import parse_upgradable
from .cishape import (
    analyze_compose,
    analyze_config_dir,
    build_row,
    code_versions,
    config_dirs,
    deploy_targets,
    is_dockerfile,
    parse_gateways,
    parse_targets,
)
from .config import RunnerConfig
from .conn import gateway_aliases, list_upgrades, list_upgrades_yum, read_file, read_file_via, run_remote, test_ssh
from .gitlab import fetch_latest_pipeline, fetch_repo_file, fetch_repo_tree
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

    {file: 경로}(대상 파일 기준 상대경로 가능) · {gitlab: repo|center, project, path, ref?} · {ssh: 호스트별칭, path}.
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
    if src.get("ssh") and src.get("path"):  # 서버에 있는 실제 파일(예: compose) — 내용은 판독만, 중앙엔 안 올림
        content, _err = read_file(str(src["ssh"]), str(src["path"]), cfg.connect_timeout)
        return True, content
    url, token = _gitlab_of(src, cfg)
    if not url or not token or not src.get("project") or not src.get("path"):
        return False, None
    text = fetch_repo_file(
        url, token, str(src["project"]), str(src["path"]), str(src.get("ref") or cfg.gitlab_ref), cfg.connect_timeout
    )
    return True, text


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


CODE_VERSION_FILES = (".nvmrc", "package.json", "pom.xml")


def _src_info(src: object, note: str | None = None, auto: bool = False) -> dict:
    """화면에 '어디서 읽었나' 를 보여주기 위한 짧은 정보(파일 내용은 안 담음)."""
    if not isinstance(src, dict):
        return {"kind": "unknown"}
    if src.get("via"):  # 게이트웨이 경유
        return {"kind": "ssh", "auto": auto, "via": src["via"], "where": f"{src['via']} → {src['ssh']}:{src.get('path')}"}
    if src.get("ssh"):
        return {"kind": "ssh", "auto": auto, "where": f"{src['ssh']}:{src.get('path')}"}
    note = src.get("note", note)  # 파일마다 note 를 달면 서비스 note 보다 우선(빈 값이면 메모 없음)
    if src.get("file"):
        return {"kind": "file", "note": note or None, "where": str(src["file"])}
    return {"kind": "gitlab", "note": note or None, "where": f"{src.get('project')}:{src.get('path')}"}


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
    ref = str(config.get("ref") or cfg.gitlab_ref)
    tree = fetch_repo_tree(url, token, str(config["project"]), ref, cfg.connect_timeout)
    if tree is None:
        return None
    return config_dirs(tree), lambda rel: fetch_repo_file(url, token, str(config["project"]), rel, ref, cfg.connect_timeout)


def cmd_shape(cfg: RunnerConfig, targets_path: str | None = None, ssh_mode: str | None = None) -> None:
    """ssh_mode: None = 대상 파일에 적힌 것만 / 'plan' = center CI 로 서버 compose 위치를 찾아 목록만 출력(접속 안 함)
    / 'read' = 그 목록대로 SSH 로 실제 읽음(대상 파일에 이미 적힌 환경은 건드리지 않음)."""
    path = targets_path or cfg.shape_targets
    if not os.path.exists(path):
        print(f"비교표 대상 파일 없음({path}) — runner/shape-targets.example.yml 을 복사해 채우세요.")
        return
    with open(path, encoding="utf-8") as f:
        targets_text = f.read()
    runners, services, config = parse_targets(targets_text)
    gateways, gateway_user = parse_gateways(targets_text)
    if not services and not config:
        print(f"비교표 대상이 비어 있음 — {path} 의 services: / config: 를 채우세요.")
        return
    base_dir = os.path.dirname(os.path.abspath(path))
    listing = _config_listing(config, cfg, base_dir) if config else None
    if config and listing is None:
        print("  config 를 읽지 못함 — config: 의 file 경로 또는 GitLab 설정을 확인하세요.")
    dirs, read_cfg = listing if listing else ({}, None)

    def config_files(cdir: str) -> tuple[str | None, str | None]:
        """config 폴더의 (Dockerfile 원문, start.sh 이름|None)."""
        names = dirs.get(cdir, [])
        df = next((n for n in names if is_dockerfile(n)), None)
        sh = next((n for n in names if re.search(r"start[\w-]*\.sh", n, re.I)), None)
        return (read_cfg(f"{cdir}/{df}") if (df and read_cfg) else None), sh

    rows, missing = [], []
    compose_by_dir: dict[str, dict[str, str | None]] = {}
    src_by_dir: dict[str, dict[str, dict]] = {}  # config 폴더 → 환경 → 어디서 읽었나
    miss_by_dir: dict[str, dict[str, dict]] = {}  # config 폴더 → 환경 → 못 읽음(이유) / 위치만 찾음
    envs_by_dir: dict[str, set[str]] = {}  # config 폴더 → 그 서비스가 배포하는 환경(비교표 기준)
    types_by_dir: dict[str, list[str]] = {}  # config 폴더 → 이 폴더를 쓰는 서비스의 표 타입(예: web 폴더를 manager·syncer 가 같이 씀)

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
    for cdir, envs in ((config or {}).get("compose") or {}).items():
        for env, src in (envs or {}).items():
            tried, text = _read_source(src, cfg, base_dir)
            if tried and text is None:
                missing.append(f"config {cdir}:compose.{env}")
                miss(str(cdir), str(env), "fail", "적어 둔 파일을 못 읽음(없음·권한·접속 실패)")
            compose_by_dir.setdefault(str(cdir), {})[str(env)] = text
            if text:
                src_by_dir.setdefault(str(cdir), {})[str(env)] = _src_info(src)
    for svc in services:
        files: dict = {}
        for key in ("repo_ci", "center_ci", "dockerfile", "startup"):
            tried, text = _read_source(svc.get(key), cfg, base_dir)
            if tried:
                files[key] = text
                if text is None and key != "startup":  # start.sh 는 '없음'이 정상 결과
                    missing.append(f"{svc['name']}:{key}")
        cdir = svc.get("config_dir")
        if cdir and cdir in dirs:  # dockerfile/startup 을 config 폴더에서 채움
            df_text, sh = config_files(cdir)
            files.setdefault("dockerfile", df_text)
            files.setdefault("startup", sh)
        compose = {}
        for env, src in (svc.get("compose") or {}).items():
            tried, text = _read_source(src, cfg, base_dir)
            if tried and text is None:
                missing.append(f"{svc['name']}:compose.{env}")
                miss(cdir, str(env), "fail", "적어 둔 파일을 못 읽음(없음·권한·접속 실패)")
            compose[str(env)] = text
            if cdir and text:
                compose_by_dir.setdefault(cdir, {}).setdefault(str(env), text)
                src_by_dir.setdefault(cdir, {}).setdefault(str(env), _src_info(src, svc.get("source_note")))
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
                    miss(cdir, env, "planned", f"위치는 찾음: {where}:{path_} — --ssh 로 읽기")
                    continue
                if not alias and not via:
                    miss(cdir, env, "fail", f"~/.ssh/config 에 직접 등록 안 된 서버 — 게이트웨이를 거쳐야 할 수 있음(gateways: 에 이 환경의 gw 를 적으면 경유) — {path_}")
                    continue
                if alias:
                    src = {"ssh": alias, "path": path_}
                    _, text = _read_source(src, cfg, base_dir)
                    fail_where = f"{alias}:{path_}"
                else:
                    # gw 에 이름으로 등록된 서버면 그 이름으로(gw 의 계정·키·지문 설정을 그대로) — 없으면 주소로
                    if via not in gw_names:
                        gw_names[via] = gateway_aliases(via, cfg.connect_timeout)
                    inner = gw_names[via].get(ip)
                    src = {"ssh": inner or ip, "via": via, "path": path_}
                    text, err = read_file_via(via, inner or ip, path_, cfg.connect_timeout, None if inner else gateway_user)
                    hint = "" if inner else " · gw 로그인 계정의 ssh 설정에 이 서버 이름이 없음(등록하면 그 설정으로 접속)"
                    fail_where = f"{via} → {inner or ip}:{path_} ({err}){hint}"
                if text is None:
                    missing.append(f"{svc['name']}:compose.{env}(ssh {alias or via})")
                    miss(cdir, env, "fail", f"SSH 로 못 읽음(접속·권한·파일 없음) — {fail_where}")
                    continue
                compose[env] = text
                if cdir:
                    compose_by_dir.setdefault(cdir, {}).setdefault(env, text)
                    src_by_dir.setdefault(cdir, {}).setdefault(env, _src_info(src, auto=True))
        files["compose"] = compose
        row = build_row(svc, files, runners)
        if cdir:
            envs_by_dir.setdefault(cdir, set()).update(row["data"]["deploy"])
            types_by_dir.setdefault(cdir, []).append(str(row["data"]["type"]))
        if cdir and svc.get("repo_ci"):
            code_files = {n: _read_source(_sibling(svc["repo_ci"], n), cfg, base_dir)[1] for n in CODE_VERSION_FILES}
            cv = code_versions(code_files)
            if cv:
                code_by_dir.setdefault(cdir, cv)
        if cdir and cdir in dirs:  # start.sh 칸 색: config 폴더 기준(실행에 씀 / 파일만 남음 / 없음)
            row["data"]["start_state"] = analyze_config_dir(dirs[cdir], config_files(cdir)[0])["state"]
        rows.append(row)

    items = []
    for cdir in sorted(dirs):
        df_text, _ = config_files(cdir)
        data = analyze_config_dir(dirs[cdir], df_text)
        moves = {env: (analyze_compose(t) or {}).get("start") for env, t in compose_by_dir.get(cdir, {}).items() if t}
        data["compose"] = {env: m for env, m in moves.items() if m}
        data["compose_src"] = {env: src_by_dir.get(cdir, {}).get(env) for env in data["compose"]}  # 칸마다 어디서 읽었나
        data["compose_miss"] = {e: m for e, m in miss_by_dir.get(cdir, {}).items() if e not in data["compose"]}
        if envs_by_dir.get(cdir):  # 여기 없는 환경엔 배포를 안 함 → 화면에서 '안 읽음' 대신 '—' (CI 를 못 읽어 비면 안 붙임 = 모름)
            data["deploy_envs"] = sorted(envs_by_dir[cdir])
        roles = [t for t in dict.fromkeys(types_by_dir.get(cdir, [])) if t != cdir.partition("/")[2]]
        if roles:  # 폴더 이름(web)과 다른 이름으로 쓰임 — 이미지 하나를 역할별로 나눠 띄움
            data["used_as"] = roles
        merged = ((config or {}).get("merged") or {}).get(cdir)
        if merged:  # 다른 폴더로 합쳐져 안 쓰는 폴더(예: repo 둘이 center 에서 하나로)
            data["merged_into"] = str(merged)
        data["code"] = code_by_dir.get(cdir)  # 코드에 적힌 버전(없으면 None)
        items.append({"path": cdir, "data": data})

    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        if services:
            res = api.upload_shapes(rows, replace=True)  # 대상 파일이 기준 — 빠진 서비스는 표에서 내림
            print(f"비교표 수집: {res['accepted']}개 서비스")
        if listing:
            res = api.upload_config(items, replace=True)
            print(f"config 수집: {res['accepted']}개 폴더")
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
        cmd_shape(cfg, args.targets, "read" if args.ssh else ("plan" if args.ssh_plan else None))
    elif args.cmd == "all":
        cmd_all(cfg, loop=args.loop, interval=args.interval)
    elif args.cmd == "apply":
        cmd_apply(cfg, dry_run=args.dry_run, rollback_id=args.rollback)


if __name__ == "__main__":
    main()
