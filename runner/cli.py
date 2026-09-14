"""러너 CLI (Phase 0).

  python -m runner.cli import   # ~/.ssh/config 파싱 → 중앙 인벤토리에 임포트
  python -m runner.cli test     # 등록 서버에 SSH 연결 테스트 → 결과 업로드
  python -m runner.cli conf     # 관리 경로 conf 수집 → 드리프트 비교
  python -m runner.cli updates  # 서버별 대기 OS 패치(apt) 수집
  python -m runner.cli versions # 빌드 서버 툴체인 버전(node/java/docker 등) 수집
  python -m runner.cli versions-repo # GitLab repo 선언본 버전 수집(CT_GITLAB_URL/TOKEN)
  python -m runner.cli cicd     # GitLab 파이프라인 상태 수집(CT_GITLAB_URL/TOKEN)

env: CT_CENTRAL_URL(기본 :8000) · CT_API_TOKEN(기본 dev-runner-token) · CT_SSH_CONFIG(기본 ~/.ssh/config)
접속 테스트는 시스템 ssh 가 ~/.ssh/config(ProxyJump·키)를 그대로 사용한다.
"""
from __future__ import annotations

import argparse
import os
import time

from .api import CentralAPI
from .apt import parse_upgradable
from .config import RunnerConfig
from .conn import list_upgrades, read_file, run_remote, test_ssh
from .gitlab import fetch_latest_pipeline, fetch_repo_file
from .repoversions import extract_versions
from .sshconf import parse_ssh_config
from .versions import PROBES, parse_version

# 선언본 후보 파일(있는 것만 파싱)
REPO_VERSION_FILES = (".nvmrc", "package.json", "pom.xml")


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


def cmd_test(cfg: RunnerConfig) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = api.list_servers()
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


def cmd_conf(cfg: RunnerConfig) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = api.list_servers()
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


def cmd_updates(cfg: RunnerConfig) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = api.list_servers()
        snaps = []
        for s in servers:
            out, err = list_upgrades(s["hostname"], cfg.connect_timeout)
            pkgs = parse_upgradable(out) if out is not None else None
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


def cmd_versions(cfg: RunnerConfig) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    try:
        servers = api.list_servers()
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


def main() -> None:
    p = argparse.ArgumentParser(prog="ct-runner", description="Control Tower 러너")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="~/.ssh/config → 중앙 인벤토리 임포트")
    imp.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력(전송 안 함)")
    sub.add_parser("test", help="등록 서버 SSH 연결 테스트")
    sub.add_parser("conf", help="관리 경로 conf 수집 → 드리프트 비교")
    sub.add_parser("updates", help="서버별 대기 OS 패치(apt) 수집")
    sub.add_parser("versions", help="빌드 서버 툴체인 버전(node/java/docker 등) 수집")
    sub.add_parser("versions-repo", help="GitLab repo 선언본 버전 수집(CT_GITLAB_URL/TOKEN 필요)")
    sub.add_parser("cicd", help="GitLab 파이프라인 상태 수집(CT_GITLAB_URL/TOKEN 필요)")
    args = p.parse_args()

    cfg = RunnerConfig.load()
    if args.cmd == "import":
        cmd_import(cfg, dry_run=args.dry_run)
    elif args.cmd == "test":
        cmd_test(cfg)
    elif args.cmd == "conf":
        cmd_conf(cfg)
    elif args.cmd == "updates":
        cmd_updates(cfg)
    elif args.cmd == "versions":
        cmd_versions(cfg)
    elif args.cmd == "versions-repo":
        cmd_versions_repo(cfg)
    elif args.cmd == "cicd":
        cmd_cicd(cfg)


if __name__ == "__main__":
    main()
