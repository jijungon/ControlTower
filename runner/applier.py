"""conf 적용 — 승인된 기준본을 서버에 실제로 쓴다. 이 도구의 유일한 '쓰기' 경로.

안전: 백업 → 임시파일 쓰기 → 원자적 mv 교체 → verify(재수집 sha). 실패 시 백업 보존.
관리 경로(conf_targets)만 대상이며 ~/.ssh/config 는 절대 건드리지 않는다(수집기와 동일).
CT_APPLY_SUDO=1 이면 cp/tee/mv 를 sudo 로 실행(root 소유 conf 대비, passwordless 전제).
"""
from __future__ import annotations

import hashlib
import shlex
import subprocess
import time

from .conn import read_file

_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _ssh(alias: str, command: str, timeout: int, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*_SSH, "-o", f"ConnectTimeout={timeout}", alias, command],
        capture_output=True,
        text=True,
        timeout=timeout + 20,
        input=input,
    )


def apply_intent(
    alias: str,
    path: str,
    content: str,
    to_sha: str,
    *,
    sudo: bool = False,
    timeout: int = 8,
    ts: str | None = None,
) -> dict:
    """기준본(content)을 서버 path 에 적용. {ok, backup_path, error} 반환."""
    ts = ts or time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.ct-backup-{ts}"
    tmp = f"{path}.ct-new-{ts}"
    pre = "sudo " if sudo else ""
    q = shlex.quote

    # 1) 백업
    r = _ssh(alias, f"{pre}cp -- {q(path)} {q(backup)}", timeout)
    if r.returncode != 0:
        return {"ok": False, "backup_path": None, "error": f"backup 실패: {r.stderr.strip() or r.returncode}"}
    # 2) 임시파일에 새 내용 쓰기(stdin → tee)
    r = _ssh(alias, f"{pre}tee -- {q(tmp)} > /dev/null", timeout, input=content)
    if r.returncode != 0:
        return {"ok": False, "backup_path": backup, "error": f"write 실패: {r.stderr.strip() or r.returncode}"}
    # 3) 원자적 교체
    r = _ssh(alias, f"{pre}mv -- {q(tmp)} {q(path)}", timeout)
    if r.returncode != 0:
        return {"ok": False, "backup_path": backup, "error": f"교체 실패: {r.stderr.strip() or r.returncode}"}
    # 4) verify (재수집 sha 비교)
    got, err = read_file(alias, path, timeout)
    if err is not None:
        return {"ok": False, "backup_path": backup, "error": f"verify 읽기 실패: {err}"}
    if _sha(got) != to_sha:
        return {"ok": False, "backup_path": backup, "error": "verify 불일치(적용 후 sha 다름)"}
    return {"ok": True, "backup_path": backup, "error": None}


def rollback(alias: str, path: str, backup_path: str, *, sudo: bool = False, timeout: int = 8) -> dict:
    """백업본을 path 로 복원. {ok, error} 반환."""
    pre = "sudo " if sudo else ""
    q = shlex.quote
    r = _ssh(alias, f"{pre}cp -- {q(backup_path)} {q(path)}", timeout)
    if r.returncode != 0:
        return {"ok": False, "error": f"복원 실패: {r.stderr.strip() or r.returncode}"}
    return {"ok": True, "error": None}
