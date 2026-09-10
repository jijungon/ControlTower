"""러너 CLI (Phase 0).

  python -m runner.cli import   # ~/.ssh/config 파싱 → 중앙 인벤토리에 임포트
  python -m runner.cli test     # 등록 서버에 SSH 연결 테스트 → 결과 업로드

env: CT_CENTRAL_URL(기본 :8000) · CT_API_TOKEN(기본 dev-runner-token) · CT_SSH_CONFIG(기본 ~/.ssh/config)
접속 테스트는 시스템 ssh 가 ~/.ssh/config(ProxyJump·키)를 그대로 사용한다.
"""
from __future__ import annotations

import argparse
import os
import time

from .api import CentralAPI
from .conn import test_ssh
from .config import RunnerConfig
from .sshconf import parse_ssh_config


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


def main() -> None:
    p = argparse.ArgumentParser(prog="ct-runner", description="Control Tower 러너")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="~/.ssh/config → 중앙 인벤토리 임포트")
    imp.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력(전송 안 함)")
    sub.add_parser("test", help="등록 서버 SSH 연결 테스트")
    args = p.parse_args()

    cfg = RunnerConfig.load()
    if args.cmd == "import":
        cmd_import(cfg, dry_run=args.dry_run)
    elif args.cmd == "test":
        cmd_test(cfg)


if __name__ == "__main__":
    main()
