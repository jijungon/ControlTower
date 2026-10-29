"""수집기가 IdP(금고) 도장으로 서버 정보를 읽는 길 (#58) — 기본 꺼짐.

켜는 설정 하나: CT_CERT_SERVERS — 읽을 서버를 금고 목록 이름으로, 쉼표로: <환경>/<서비스>/<서버>
  비면 꺼짐(기본). 주소는 여기에 적지 않는다 — 수집할 때마다 api 가 금고 목록(inventory/<환경>/<서비스> 의
  servers)에서 그 이름의 주소를 준다. 목록에 없으면 추측하지 않고 '목록에 없음' 으로 남긴다.
  (수집기 신분 ct-collector 는 목록을 못 읽는다 — 목록은 api 의 ct-inventory 몫)

한 번 수집:
  1) 임시 폴더(0700)에 새 키 한 쌍(ed25519)을 만든다 — 서버에도 이 컨테이너에도 오래 사는 열쇠를 두지 않는다
  2) 금고 로그인(비밀 파일을 이때 읽음) → 대상 서버의 환경마다 도장 한 번(15분)
  3) 서버마다 appuser 로: OS 패치(apt, 없으면 dnf/yum) · 관리 경로 파일(cat) — 도장에 박힌 세 명령만
  4) 임시 폴더(키 · 도장)를 지운다

도장은 박힌 세 명령 밖을 rc 126 + 'idp-collect: …' 로 거절한다 → '이 길로는 못 읽음'(conn.BLOCKED) —
'오류' 도 '정상(값 없음)' 도 아니다. 박힌 규칙 밖인 경로(/etc 아래 · compose 파일이 아님)는 아예 보내지 않고
같은 표시로 남긴다. 버전 확인(node --version 등)은 이 길로 안 되므로 시도하지 않는다.
회사 서버(gw 뒤)는 아직 아니다 — 수집기에서 바로 22번으로 닿는 서버만.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import signer
from .conn import BLOCKED, read_file, read_updates

ENVS = signer.ENVS
SSH_USER = "appuser"  # 도장의 꼬리표 <환경>-appuser 가 들어가는 계정
# 금고 목록의 주소 — IPv4 · IPv6 · 호스트 이름만 (api 의 목록 고치기와 같은 선). '-' 로 시작하면 ssh 옵션이 된다
_ADDR = re.compile(r"^(?!-)[A-Za-z0-9.:-]{1,253}$")
# 도장에 박힌 cat 규칙과 같은 선 — 글자는 영문 · 숫자 · _ . / @ + - 만, '..' 안 됨, /etc 아래 또는 compose 파일
_SAFE = re.compile(r"^[A-Za-z0-9_./@+-]*$")
_COMPOSE = re.compile(r"^/.*/(docker-compose\.ya?ml|docker-compose\..*\.yml|compose\.ya?ml)$")


def picks(text: str | None) -> tuple[list[str], list[str]]:
    """CT_CERT_SERVERS → (쓸 이름들, 모양이 틀린 것들). 이름 = <환경>/<서비스>/<서버>, 환경은 dev · stg · prod."""
    good: list[str] = []
    bad: list[str] = []
    for raw in (text or "").split(","):
        item = raw.strip()
        if not item:
            continue
        parts = item.split("/")
        if len(parts) == 3 and parts[0] in ENVS and all(parts):
            if item not in good:
                good.append(item)
        else:
            bad.append(item)
    return good, bad


def path_ok(path: str) -> bool:
    """이 경로를 도장 길로 보내도 되나 — 금고에 박힌 cat 규칙을 그대로 옮긴 것(밖이면 보내지 않음)."""
    if not _SAFE.match(path) or ".." in path:
        return False
    return path.startswith("/etc/") or bool(_COMPOSE.match(path))


class CertSession:
    """한 번 수집 동안의 임시 키 · 환경별 도장. with 가 끝나면 폴더째 지운다."""

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.dir = tempfile.mkdtemp(prefix="ct-cert-")  # 0700
        self.key = os.path.join(self.dir, "key")
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ct-collector", "-f", self.key],
            check=True, capture_output=True, timeout=30,
        )
        self.public_key = Path(self.key + ".pub").read_text()
        self._token: str | None = None
        self._certs: dict[str, str] = {}
        self._errors: dict[str, str] = {}

    def __enter__(self) -> "CertSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def cert(self, env: str) -> tuple[str | None, str | None]:
        """(도장 파일 경로, 못 받은 까닭). 환경마다 한 번만 받는다. 로그인은 수집 한 번에 한 번(비밀 파일을 그때 읽음)."""
        if env in self._certs:
            return self._certs[env], None
        if env in self._errors:
            return None, self._errors[env]
        try:
            if self._token is None:
                self._token = signer.login()
            signed = signer.sign(env, self.public_key, self._token)
        except signer.SignerError as exc:
            self._errors[env] = str(exc)
            return None, str(exc)
        path = os.path.join(self.dir, f"{env}-cert.pub")
        Path(path).write_text(signed)
        self._certs[env] = path
        return path, None

    def ssh_argv(self, cert: str, addr: str) -> list[str]:
        """호스트까지의 ssh 앞부분. 설정 파일(-F none) · 에이전트 · 다른 키는 안 씀 — 이 키 + 이 도장 하나로만."""
        return [
            "ssh", "-F", "none",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.timeout}",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none",
            "-i", self.key,
            "-o", f"CertificateFile={cert}",
            "-l", SSH_USER,
            addr,
        ]


def _register(api: Any, servers: list[dict]) -> dict[str, int]:
    """중앙 서버 목록에 '<환경>/<서비스>/<서버>' 이름으로 올리고(있으면 주소만 고침) → {이름: server_id}."""
    api.import_servers([
        {"hostname": s["pick"], "ip": s["addr"], "ssh_user": SSH_USER, "ssh_port": 22} for s in servers
    ])
    return {x["hostname"]: x["id"] for x in api.list_servers() if x["hostname"] in {s["pick"] for s in servers}}


def collect(cfg: Any, api: Any, plan: bool = False) -> dict:
    """CT_CERT_SERVERS 의 서버를 도장으로 읽어 OS 패치 · 관리 경로 파일을 올린다 → {ok, message}.

    plan=True 면 목록에서 찾기까지만(로그인 · 접속 안 함).
    ok=False — 길 전체가 막혔을 때(목록을 못 받음 · 도장을 못 받음). 서버 하나가 안 닿는 것은 그 서버 칸에 까닭.
    """
    want, bad = picks(getattr(cfg, "cert_servers", ""))
    notes = [f"이름 모양이 틀림: {', '.join(bad)}"] if bad else []
    if not want:
        return {"ok": not bad, "message": " · ".join(["도장 길: 대상 없음", *notes])}
    got = api.collect_servers(want)
    if got.get("state") != "ok":
        why = "금고 목록 연결 꺼짐(CT_INVENTORY_MODE)" if got.get("state") == "off" else (got.get("error") or got.get("state"))
        print(f"  도장 길: 금고 목록을 못 받음 — {why}")
        return {"ok": False, "message": f"도장 길: 금고 목록을 못 받음({why})"[:200]}
    servers = []
    for s in got.get("servers") or []:
        pick = f"{s['env']}/{s['service']}/{s['name']}"
        if pick in want:
            servers.append({**s, "pick": pick})
    missing = [p for p in want if p not in {s["pick"] for s in servers}]
    if missing:
        notes.append(f"목록에 없음: {', '.join(missing)}")
        print(f"  도장 길: 금고 목록에 없음 — {', '.join(missing)} (이름을 추측하지 않음)")
    for s in servers:
        print(f"  도장 길: {s['pick']} → {s['addr']} ({s['env']} 도장 · {SSH_USER})")
    if plan:
        return {"ok": not missing and not bad, "message": " · ".join([f"도장 길: 찾음 {len(servers)}대", *notes])}
    if not servers:
        return {"ok": False, "message": " · ".join(["도장 길: 읽을 서버 없음", *notes])}

    ids = _register(api, servers)
    paths = api.list_conf_targets()
    upd, confs = [], []
    sign_fail: list[str] = []
    counts = {"read": 0, "blocked": 0, "fail": 0}
    with CertSession(getattr(cfg, "connect_timeout", 8)) as sess:
        for s in servers:
            sid = ids.get(s["pick"])
            if sid is None:
                notes.append(f"중앙 서버 목록에 못 올림: {s['pick']}")
                continue
            cert, err = sess.cert(s["env"])
            if cert is None:
                err = f"도장을 못 받음 — {err}"
                sign_fail.append(f"{s['env']}: {err}")
            elif not _ADDR.match(str(s["addr"])):
                cert, err = None, "목록의 주소 모양이 이상해 접속하지 않음"
            if cert is None:  # 못 읽은 것도 까닭과 함께 올린다 — 지난 값이 '정상' 으로 남아 보이지 않게
                upd.append({"server_id": sid, "packages": None, "error": err})
                confs += [{"server_id": sid, "path": p, "content": None, "error": err} for p in paths]
                counts["fail"] += 1
                print(f"  ✗ {s['pick']}: {err}")
                continue
            ssh = sess.ssh_argv(cert, str(s["addr"]))
            pkgs, err = read_updates(s["pick"], sess.timeout, ssh)
            upd.append({"server_id": sid, "packages": pkgs, "error": err})
            for p in paths:
                if not path_ok(p):  # 도장에 박힌 규칙 밖 — 보내 봐야 거절된다
                    content, perr = None, BLOCKED + "박힌 규칙 밖의 경로(/etc 아래 · compose 파일만) — 보내지 않음"
                else:
                    content, perr = read_file(s["pick"], p, sess.timeout, ssh)
                confs.append({"server_id": sid, "path": p, "content": content, "error": perr})
            errs = [x for x in [err, *(c["error"] for c in confs if c["server_id"] == sid)] if x]
            if any(not e.startswith(BLOCKED) for e in errs):
                counts["fail"] += 1
            elif errs:
                counts["blocked"] += 1
            else:
                counts["read"] += 1
            for e in errs:
                print(f"  ✗ {s['pick']}: {e}")
    if upd:
        api.upload_update_snapshots(upd)
    if confs:
        api.upload_conf_snapshots(confs)
    head = f"도장 길: {len(servers)}대 — 다 읽음 {counts['read']} · 일부 이 길로는 못 읽음 {counts['blocked']} · 못 읽음 {counts['fail']}"
    if sign_fail:
        notes.append(sign_fail[0])
    return {"ok": not sign_fail and not missing and not bad, "message": " · ".join([head, *notes])[:300]}
