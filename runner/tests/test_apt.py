"""apt 파서 단위 테스트."""
from runner.apt import parse_upgradable

SAMPLE = """Listing...
openssl/jammy-updates,jammy-security 3.0.13 amd64 [upgradable from: 3.0.2]
vim/jammy-updates 8.2.5172 amd64 [upgradable from: 8.2.3995]
garbage line without a match
"""


def test_parse_upgradable():
    assert parse_upgradable(SAMPLE) == [
        {"name": "openssl", "from": "3.0.2", "to": "3.0.13", "security": True},
        {"name": "vim", "from": "8.2.3995", "to": "8.2.5172", "security": False},
    ]


def test_parse_empty():
    assert parse_upgradable("Listing...\n") == []
    assert parse_upgradable("") == []
