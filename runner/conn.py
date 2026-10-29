"""접속 테스트 — 시스템 ssh 로 ~/.ssh/config 를 그대로 활용(ProxyJump·IdentityFile 포함).

별도 키스토어 없이, 사용자의 기존 ssh 설정으로 접속되는지만 확인한다.
"""
from __future__ import annotations

import shlex
import subprocess

from .access import ssh_access_opts
from .apt import parse_upgradable
from .yum import parse_yum

# ── IdP 수집기 도장(#58)에 박힌 명령과 **한 글자도** 다르면 안 되는 글 ──
# ssh 는 호스트 뒤 argv 를 공백으로 이어 한 줄로 보낸다. 금고는 그 한 줄이 아래 셋 중 하나일 때만 돌리고,
# 그 밖은 rc 126 + stderr 'idp-collect: …' 로 거절한다. 바꾸면 금고 쪽 박힌 명령도 같이 바꿔야 한다.
APT_UPGRADABLE = ("apt", "list", "--upgradable")
YUM_CHECK_UPDATE = "sh -lc 'command -v dnf >/dev/null 2>&1 && dnf -q check-update || yum -q check-update'"
# 도장이 거절한 것 — '오류'(접속 · 권한)도 '정상(값 없음)'도 아닌 '이 길로는 못 읽음'. 중앙이 이 머리글로 가른다
# (central/api/app/routers/updates.py · conf.py 의 BLOCKED 와 같은 글)
BLOCKED = "이 길(도장)로는 못 읽음 — "
REFUSED_RC = 126
REFUSED_MARK = "idp-collect:"


def _why(rc: int, stderr: str) -> str:
    """실패 까닭 한 줄. 도장이 거절했으면(rc 126 + 'idp-collect:') BLOCKED 머리글을 붙인다 — 둘 다일 때만."""
    lines = [ln.strip() for ln in (stderr or "").strip().splitlines() if ln.strip()]
    refused = next((ln for ln in lines if ln.startswith(REFUSED_MARK)), None)
    if rc == REFUSED_RC and refused:
        return BLOCKED + refused
    return lines[-1] if lines else f"exit {rc}"


def _ssh_argv(alias: str, timeout: int) -> list[str]:
    """모든 조회가 공유하는 ssh 프리픽스. 접속 수단(key/cert)은 access 어댑터가 결정한다."""
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        "-o", "StrictHostKeyChecking=accept-new",
        *ssh_access_opts(alias),
        alias,
    ]


def test_ssh(alias: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                "true",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 6,
        )
        if r.returncode == 0:
            return True, ""
        err = r.stderr.strip()
        return False, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "ssh not found"


def read_file(alias: str, path: str, timeout: int = 8, ssh: list[str] | None = None) -> tuple[str | None, str | None]:
    """서버의 파일 내용을 읽는다(시스템 ssh cat). (content, error) — 실패 시 (None, error).

    ssh = 호스트까지 포함한 ssh 앞부분(도장 길 — runner/certpath.py). 없으면 ~/.ssh/config 별칭(alias)으로.
    """
    try:
        r = subprocess.run(
            [
                *(ssh or _ssh_argv(alias, timeout)),
                "cat", "--", path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if r.returncode == 0:
            return r.stdout, None
        return None, _why(r.returncode, r.stderr)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def parse_ssh_aliases(text: str) -> dict[str, str]:
    """ssh 설정 글 → {HostName(주소): Host 이름}. 와일드카드(*, ?) Host 는 뺌, 같은 주소면 먼저 나온 이름."""
    out: dict[str, str] = {}
    names: list[str] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key, val = parts[0].lower(), parts[1].strip()
        if key == "host":
            names = [n for n in val.split() if not any(c in n for c in "*?!")]
        elif key == "hostname" and names:
            out.setdefault(val, names[0])
    return out


def gateway_aliases(gateway: str, timeout: int = 8, sudo: bool = False) -> dict[str, str]:
    """게이트웨이 로그인 계정의 ~/.ssh/config 를 읽어 {주소: 이름}. 읽기만 한다(cat). 못 읽으면 {}.

    gw 에 이름으로 등록된 서버는 그 이름으로 들어가야 gw 가 맞춰 둔 계정·키·지문(known_hosts)을 그대로 쓴다.
    sudo = 서버들이 gw 의 root 계정에만 등록된 경우 — root 의 설정을 `sudo -n` 으로 읽는다(비밀번호를 묻지 않음).
    """
    cmd = "sudo -n cat /root/.ssh/config" if sudo else "cat ~/.ssh/config"
    try:
        r = subprocess.run([*_ssh_argv(gateway, timeout), cmd], capture_output=True, text=True, timeout=timeout + 15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    return parse_ssh_aliases(r.stdout) if r.returncode == 0 else {}


def read_file_via(
    gateway: str, target: str, path: str, timeout: int = 8, user: str | None = None, sudo: bool = False
) -> tuple[str | None, str | None]:
    """게이트웨이를 거쳐 안쪽 서버의 파일을 읽는다: PC → gateway(~/.ssh/config 별칭) → gw 위에서 ssh target cat.

    안쪽 접속은 gw 자신의 ssh 설정·키를 그대로 쓴다(ControlTower 원래 설계: 서버 키는 gw 에).
    BatchMode·ConnectTimeout 만 주고 호스트 키 정책은 gw 설정을 따른다 — gw 의 known_hosts 를 새로 쓰지 않게.
    읽기만 한다(cat). (content, error).
    sudo = gw 의 root 계정 ssh 설정·키로 안쪽에 들어감(`sudo -n ssh …`, 비밀번호를 묻지 않음 — 안 되면 실패로).
    """
    dest = f"{user}@{target}" if user else target
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", dest, "cat", "--", path]
    inner = " ".join(shlex.quote(a) for a in (["sudo", "-n", *argv] if sudo else argv))
    try:
        r = subprocess.run(
            [*_ssh_argv(gateway, timeout), inner],
            capture_output=True,
            text=True,
            timeout=timeout * 2 + 15,
        )
        if r.returncode == 0:
            return r.stdout, None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def run_remote(alias: str, command: str, timeout: int = 8) -> tuple[str | None, str | None]:
    """원격 명령을 실행하고 출력을 읽는다(조회 용도). (stdout+stderr, error).

    버전 프로브(`node --version`, `java -version` 등)에 사용 — 서버를 변경하지 않는다.
    버전은 stdout/stderr 어느 쪽이든 나올 수 있어 둘을 합쳐 돌려준다.
    """
    try:
        r = subprocess.run(
            [
                *_ssh_argv(alias, timeout),
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if r.returncode == 0:
            return (r.stdout or "") + (r.stderr or ""), None
        err = r.stderr.strip()
        return None, (err.splitlines()[-1] if err else f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def list_upgrades_yum(alias: str, timeout: int = 8, ssh: list[str] | None = None) -> tuple[str | None, str | None]:
    """yum/dnf 업그레이드 목록(조회만). rc 100=업데이트 있음(정상), 0=없음. dnf 우선, 없으면 yum."""
    try:
        r = subprocess.run(
            [
                *(ssh or _ssh_argv(alias, timeout)),
                YUM_CHECK_UPDATE,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )
        if r.returncode in (0, 100):   # yum/dnf: 100 = 업데이트 있음
            return r.stdout, None
        return None, _why(r.returncode, r.stderr)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def list_upgrades(alias: str, timeout: int = 8, ssh: list[str] | None = None) -> tuple[str | None, str | None]:
    """대기 중인 apt 업그레이드 목록을 읽는다(`apt list --upgradable`). (stdout, error).

    읽기 전용 조회다 — 서버를 변경하지 않는다(설치·업그레이드 안 함).
    apt 는 stderr 로 "unstable CLI" 경고를 내지만 rc 0·stdout 목록은 유효하다.
    """
    try:
        r = subprocess.run(
            [
                *(ssh or _ssh_argv(alias, timeout)),
                *APT_UPGRADABLE,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 20,
        )
        if r.returncode == 0:
            return r.stdout, None
        return None, _why(r.returncode, r.stderr)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "ssh not found"


def read_updates(alias: str, timeout: int = 8, ssh: list[str] | None = None) -> tuple[list[dict] | None, str | None]:
    """대기 OS 패치 → (패키지들, 오류). apt 가 없으면(not found) dnf/yum 으로 한 번 더. 못 읽으면 (None, 까닭)."""
    out, err = list_upgrades(alias, timeout, ssh)
    if out is not None:
        return parse_upgradable(out), None
    if err and "not found" in err.lower():   # apt 없음 → yum/dnf 폴백
        yout, yerr = list_upgrades_yum(alias, timeout, ssh)
        if yout is not None:
            return parse_yum(yout), None
        return None, yerr
    return None, err
