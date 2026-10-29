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
    gitlab_url: str = ""        # self-hosted GitLab (CI/CD·선언본 수집용, 예: https://gitlab.example.com)
    gitlab_token: str = ""      # GitLab PRIVATE-TOKEN (러너 로컬에만 — 중앙 저장 안 함)
    gitlab_ref: str = ""        # 읽을 브랜치 — 비우면 프로젝트마다 GitLab 기본 브랜치(main·dev 등)
    gitlab_center_url: str = ""    # center GitLab (repo 와 다른 인스턴스). 비교표(shape) 수집용
    gitlab_center_token: str = ""  # center PRIVATE-TOKEN (러너 로컬에만)
    shape_targets: str = "shape-targets.yml"  # 비교표 대상 목록(로컬 파일, 커밋 안 함)
    apply_sudo: bool = False    # conf 적용 시 sudo 사용(root 소유 파일). CT_APPLY_SUDO=1
    # 서버가 스스로 적는 상태 파일(IdP 서버 status.json) — 수집기가 읽어 화면 맨 위에. 빈 값이면 이 기능을 끔
    idp_status_file: str = "/idp-status/status.json"
    # 사람 이름표(Authentik 의 server-admin · developer) — IdP 서버가 5분마다 씀, 서버 탭 · 접속 기록 탭의 이름에. 빈 값이면 끔
    idp_people_file: str = "/idp-status/people.jsonl"
    # 금고(IdP) 접속 기록 요약 파일 — IdP 서버가 1분마다 최근 14일치를 씀, '접속 기록' 탭에. 빈 값이면 끔
    idp_access_file: str = "/idp-status/access.jsonl"
    # gw 에 실제로 들어간 기록(같은 폴더, IdP 서버가 1분마다 씀) — 위 발급 기록과 인증서 번호로 이어 붙임. 빈 값이면 끔
    idp_gw_logins_file: str = "/idp-status/gw-logins.jsonl"
    # gw 뒤 서버에 실제로 들어간 기록(같은 폴더, gw 가 읽어 보낸 서버 sshd 기록) — 위 둘과 인증서 번호로 이어 붙임. 빈 값이면 끔
    idp_server_logins_file: str = "/idp-status/server-logins.jsonl"

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
            gitlab_url=os.environ.get("CT_GITLAB_URL", ""),
            gitlab_token=os.environ.get("CT_GITLAB_TOKEN", ""),
            gitlab_ref=os.environ.get("CT_GITLAB_REF", ""),
            gitlab_center_url=os.environ.get("CT_GITLAB_CENTER_URL", ""),
            gitlab_center_token=os.environ.get("CT_GITLAB_CENTER_TOKEN", ""),
            shape_targets=os.path.expanduser(os.environ.get("CT_SHAPE_TARGETS", "shape-targets.yml")),
            apply_sudo=os.environ.get("CT_APPLY_SUDO", "") not in ("", "0", "false", "False"),
            idp_status_file=os.environ.get("CT_IDP_STATUS_FILE", "/idp-status/status.json").strip(),
            idp_people_file=os.environ.get("CT_IDP_PEOPLE_FILE", "/idp-status/people.jsonl").strip(),
            idp_access_file=os.environ.get("CT_IDP_ACCESS_FILE", "/idp-status/access.jsonl").strip(),
            idp_gw_logins_file=os.environ.get("CT_IDP_GW_LOGINS_FILE", "/idp-status/gw-logins.jsonl").strip(),
            idp_server_logins_file=os.environ.get("CT_IDP_SERVER_LOGINS_FILE", "/idp-status/server-logins.jsonl").strip(),
        )
