"""러너 설정 — 중앙 API 주소·토큰·로컬 키스토어 경로."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RunnerConfig:
    central_url: str                        # 중앙 API 베이스 URL (사내망)
    api_token: str                          # 러너 인증 토큰
    keystore_path: str                      # 로컬 키 매핑(alias -> 키). 중앙엔 없음.
    runner_name: str = "local-runner"
    max_concurrency_per_gateway: int = 5    # gw별 동시 접속 상한(대규모·15 gw 대비)
    connect_timeout: int = 10

    @classmethod
    def load(cls) -> "RunnerConfig":
        # TODO: ~/.controltower/runner.toml 로드 지원. 지금은 env 폴백.
        return cls(
            central_url=os.environ["CT_CENTRAL_URL"],
            api_token=os.environ["CT_API_TOKEN"],
            keystore_path=os.environ.get(
                "CT_KEYSTORE", os.path.expanduser("~/.controltower/keystore.toml")
            ),
            runner_name=os.environ.get("CT_RUNNER_NAME", "local-runner"),
        )
