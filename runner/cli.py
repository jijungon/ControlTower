"""러너 CLI 엔트리포인트.

Phase 0:  ct-runner test   — 전 서버 SSH 연결 테스트 후 결과를 중앙에 업로드.
실행:     python -m runner.cli test
필요 env: CT_CENTRAL_URL, CT_API_TOKEN  (키스토어: ~/.controltower/keystore.toml)
"""
from __future__ import annotations

import argparse
import asyncio

from .api import CentralAPI
from .config import RunnerConfig
from .keystore import KeyStore
from .ssh import Server, SSHRunner


def _to_server(d: dict, by_id: dict[int, dict]) -> Server:
    gw = None
    if d.get("access_method") == "via_gateway" and d.get("gateway_id"):
        gw = _to_server(by_id[d["gateway_id"]], by_id)
    return Server(
        id=d["id"],
        hostname=d["hostname"],
        ssh_port=d.get("ssh_port", 22),
        ssh_user=d["ssh_user"],
        access_method=d.get("access_method", "direct"),
        credential_alias=d.get("credential_alias"),
        gateway=gw,
    )


async def cmd_test(cfg: RunnerConfig) -> None:
    api = CentralAPI(cfg.central_url, cfg.api_token)
    ks = KeyStore(cfg.keystore_path)
    ssh = SSHRunner(ks, cfg.connect_timeout, cfg.max_concurrency_per_gateway)
    try:
        servers = await api.list_servers()
        by_id = {s["id"]: s for s in servers}
        targets = [s for s in servers if s.get("role") != "gateway"]
        results = await asyncio.gather(
            *(ssh.test_connection(_to_server(s, by_id)) for s in targets)
        )
        ok = sum(1 for r in results if r["ok"])
        print(f"연결 테스트: {ok}/{len(results)} OK")
        for r in results:
            if not r["ok"]:
                print(f"  ✗ server {r['server_id']}: {r['error']}")
        await api.post_connection_tests(results)
    finally:
        await api.aclose()


def main() -> None:
    p = argparse.ArgumentParser(prog="ct-runner", description="Control Tower 러너")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test", help="전 서버 SSH 연결 테스트 (Phase 0)")
    # TODO(Phase 1): sub.add_parser("collect", ...)  버전·conf·인증서 수집
    args = p.parse_args()

    cfg = RunnerConfig.load()
    if args.cmd == "test":
        asyncio.run(cmd_test(cfg))


if __name__ == "__main__":
    main()
