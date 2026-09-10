"""자격증명 별칭(alias) -> 로컬 키 경로 매핑.

키/비밀번호의 실체는 러너(local)에만 존재한다. 중앙 DB에는 alias 만 있다.
keystore.toml 예시는 keystore.example.toml 참고.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass


@dataclass
class Credential:
    alias: str
    username: str
    key_path: str
    passphrase: str | None = None


class KeyStore:
    def __init__(self, path: str):
        self._creds: dict[str, Credential] = {}
        self._load(path)

    def _load(self, path: str) -> None:
        if not os.path.exists(path):
            # TODO: 경고 로깅. 키스토어 없으면 모든 접속이 실패한다.
            return
        with open(path, "rb") as f:
            data = tomllib.load(f)
        for alias, v in data.items():
            self._creds[alias] = Credential(
                alias=alias,
                username=v["username"],
                key_path=os.path.expanduser(v["key_path"]),
                passphrase=v.get("passphrase"),
            )

    def resolve(self, alias: str | None) -> Credential:
        if not alias or alias not in self._creds:
            raise KeyError(f"키스토어에 없는 alias: {alias!r}")
        return self._creds[alias]
