"""버전 파서 단위 테스트."""
from runner.versions import parse_version


def test_node():
    assert parse_version("node", "v20.11.1\n") == "20.11.1"


def test_npm():
    assert parse_version("npm", "10.2.4\n") == "10.2.4"


def test_java_from_stderr():
    raw = 'openjdk version "17.0.9" 2023-10-17\nOpenJDK Runtime Environment (build 17.0.9+9)\n'
    assert parse_version("java", raw) == "17.0.9"


def test_docker():
    assert parse_version("docker", "Docker version 24.0.7, build afdd53b") == "24.0.7"


def test_python():
    assert parse_version("python", "Python 3.11.6") == "3.11.6"


def test_not_found():
    assert parse_version("node", "bash: node: command not found") is None
    assert parse_version("node", "") is None
