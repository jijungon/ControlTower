"""러너 키스토어 단위 테스트 — alias → 로컬 키 매핑 파싱."""
import pytest

from runner.keystore import KeyStore


def test_resolve(tmp_path):
    f = tmp_path / "keystore.toml"
    f.write_text('[gw-prod]\nusername = "deploy"\nkey_path = "~/.ssh/gw_prod"\n')
    ks = KeyStore(str(f))
    cred = ks.resolve("gw-prod")
    assert cred.username == "deploy"
    assert cred.key_path.endswith("gw_prod")  # ~ 확장됨


def test_missing_alias_raises(tmp_path):
    ks = KeyStore(str(tmp_path / "absent.toml"))
    with pytest.raises(KeyError):
        ks.resolve("nope")
