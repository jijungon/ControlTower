"""비밀 어댑터(secret_source) 테스트 — env(기본, no-op) + vault(가짜 KV, OpenBao 없이)."""
import json
import os

from app import secret_source


def test_env_mode_is_default_and_noop(monkeypatch):
    monkeypatch.delenv("CT_SECRET_MODE", raising=False)
    assert secret_source.secret_mode() == "env"
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    secret_source.hydrate_from_vault()  # env 모드 → 아무것도 안 함
    assert os.getenv("CT_TESTSECRET_XYZ") is None


def test_vault_mode_unconfigured_is_noop(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.delenv("CT_VAULT_ADDR", raising=False)  # 미설정
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") is None


def test_vault_mode_injects_env(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "secret/data/controltower")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    monkeypatch.setattr(
        secret_source, "_fetch_kv", lambda addr, path, token: {"CT_TESTSECRET_XYZ": "from-vault"}
    )
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") == "from-vault"


def test_vault_does_not_override_explicit_env(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "p")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.setenv("CT_TESTSECRET_XYZ", "explicit")  # 이미 설정됨
    monkeypatch.setattr(
        secret_source, "_fetch_kv", lambda addr, path, token: {"CT_TESTSECRET_XYZ": "from-vault"}
    )
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") == "explicit"  # setdefault → 안 덮음


def test_fetch_kv_parses_v2(monkeypatch):
    """KV v2 응답(data.data) 파싱 — urlopen 을 가짜로."""

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = {"data": {"data": {"CT_API_TOKEN": "v2tok"}}}
    monkeypatch.setattr(
        secret_source.urllib.request, "urlopen", lambda req, timeout=5: FakeResp(payload)
    )
    got = secret_source._fetch_kv("https://bao.local", "secret/data/ct", "tkn")
    assert got == {"CT_API_TOKEN": "v2tok"}
