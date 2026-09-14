"""yum/dnf check-update 파서 테스트."""
from runner.yum import parse_yum

SAMPLE = """Loaded plugins: fastestmirror
Obsoleting Packages
bind.x86_64          32:9.11.4-26.P2.el7_9.16   updates
bind-libs.x86_64     32:9.11.4-26.P2.el7_9.16   updates
kernel.x86_64        3.10.0-1160.119.1.el7      updates
noise line
"""


def test_parse_yum():
    p = parse_yum(SAMPLE)
    names = [x["name"] for x in p]
    assert "bind" in names and "bind-libs" in names and "kernel" in names
    b = next(x for x in p if x["name"] == "bind")
    assert b["to"].endswith("el7_9.16") and b["from"] == "" and b["security"] is False
    assert "noise" not in names  # 2컬럼 잡음 줄 제외


def test_parse_yum_empty():
    assert parse_yum("") == []
    assert parse_yum("Loaded plugins: x\nObsoleting Packages\n") == []
