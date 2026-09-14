"""선언본 버전 파서 단위 테스트."""
from runner.repoversions import extract_versions, parse_nvmrc, parse_package_json, parse_pom_java


def test_parse_nvmrc():
    assert parse_nvmrc("v20.11.1\n") == "20.11.1"
    assert parse_nvmrc("20\n") == "20"
    assert parse_nvmrc("lts/iron\n") is None


def test_parse_package_json():
    pkg = '{"engines":{"node":">=20"},"dependencies":{"@nestjs/core":"^10.3.0"}}'
    assert parse_package_json(pkg) == {"node": "20", "nest": "10.3.0"}


def test_parse_package_json_bad():
    assert parse_package_json("not json") == {}


def test_parse_pom_java():
    assert parse_pom_java("<properties><java.version>17</java.version></properties>") == "17"
    assert parse_pom_java("<maven.compiler.source>11</maven.compiler.source>") == "11"
    assert parse_pom_java("<no/>") is None


def test_extract_nvmrc_overrides_engines():
    files = {
        ".nvmrc": "18.19.1",
        "package.json": '{"engines":{"node":">=20"},"dependencies":{"@nestjs/core":"^10.3.0"}}',
        "pom.xml": None,
    }
    assert extract_versions(files) == {"node": "18.19.1", "nest": "10.3.0"}


def test_extract_java_only():
    files = {".nvmrc": None, "package.json": None, "pom.xml": "<java.version>17</java.version>"}
    assert extract_versions(files) == {"java": "17"}
