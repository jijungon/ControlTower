"""GitLab 파이프라인 조회 단위 테스트(httpx MockTransport)."""
import httpx

from runner.gitlab import fetch_latest_pipeline, fetch_repo_file, fetch_repo_tree


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


def test_fetch_repo_file_raw():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["PRIVATE-TOKEN"] == "tok"
        assert "/repository/files/package.json/raw" in str(req.url)
        assert "ref=main" in str(req.url)
        return httpx.Response(200, text='{"engines":{"node":"20"}}')

    txt = fetch_repo_file("http://gl", "tok", "group/repo", "package.json", "main", transport=_t(handler))
    assert txt == '{"engines":{"node":"20"}}'


def test_fetch_repo_file_missing_returns_none():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "404 File Not Found"})

    assert fetch_repo_file("http://gl", "tok", "group/repo", ".nvmrc", transport=_t(handler)) is None


def test_repo_tree_paginates_and_keeps_blobs():
    pages = {
        "1": ([{"type": "tree", "path": "shop"}, {"type": "blob", "path": "shop/web/Dockerfile"}], "2"),
        "2": ([{"type": "blob", "path": "shop/web/node-startup.sh"}], ""),
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert "/repository/tree" in str(req.url) and req.url.params["recursive"] == "true"
        body, nxt = pages[req.url.params["page"]]
        return httpx.Response(200, json=body, headers={"X-Next-Page": nxt})

    assert fetch_repo_tree("http://gl", "tok", "grp/config", transport=_t(handler)) == [
        "shop/web/Dockerfile",
        "shop/web/node-startup.sh",
    ]


def test_repo_tree_error_is_none():
    assert fetch_repo_tree("http://gl", "tok", "x", transport=_t(lambda r: httpx.Response(404))) is None
