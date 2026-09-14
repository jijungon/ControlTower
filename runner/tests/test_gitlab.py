"""GitLab 파이프라인 조회 단위 테스트(httpx MockTransport)."""
import httpx

from runner.gitlab import fetch_latest_pipeline


def _t(handler):
    return httpx.MockTransport(handler)


def test_latest_pipeline_found():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["PRIVATE-TOKEN"] == "tok"
        assert "/api/v4/projects/group%2Frepo/pipelines" in str(req.url)  # 경로 인코딩
        return httpx.Response(200, json=[{"status": "success", "ref": "main", "sha": "abc", "web_url": "http://gl/p/1"}])

    p = fetch_latest_pipeline("http://gl", "tok", "group/repo", transport=_t(handler))
    assert p == {"status": "success", "ref": "main", "sha": "abc", "web_url": "http://gl/p/1"}


def test_no_pipelines_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert fetch_latest_pipeline("http://gl", "tok", "group/repo", transport=_t(handler)) is None


def test_project_not_found_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "404 Project Not Found"})

    assert fetch_latest_pipeline("http://gl", "tok", "nope", transport=_t(handler)) is None
