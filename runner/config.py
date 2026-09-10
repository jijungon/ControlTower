"""러너 설정 — 환경변수 + .env 에서 주입."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class RunnerConfig:
    central_url: str            # 중앙 API (사내망)
    api_token: str              # 러너↔중앙 공유 토큰 (CT_API_TOKEN)
    ssh_config: str             # ~/.ssh/config 경로
    keystore_path: str          # (예비) alias→키. Phase 0 은 시스템 ssh 사용
    runner_name: str = "local-runner"
    connect_timeout: int = 8

    @classmethod
    def load(cls) -> "RunnerConfig":
        load_dotenv()  # 현재 디렉토리의 .env 주입 (없으면 무시)
        return cls(
            central_url=os.environ.get("CT_CENTRAL_URL", "http://127.0.0.1:8000"),
            api_token=os.environ.get("CT_API_TOKEN", "dev-runner-token"),
            ssh_config=os.environ.get("CT_SSH_CONFIG", "~/.ssh/config"),
            keystore_path=os.environ.get(
                "CT_KEYSTORE", os.path.expanduser("~/.controltower/keystore.toml")
            ),
            runner_name=os.environ.get("CT_RUNNER_NAME", "local-runner"),
        )
