"""GitLab 파이프라인 조회 단위 테스트(httpx MockTransport)."""
import httpx

from runner.gitlab import (
    fetch_job_log_head,
    fetch_latest_pipeline,
    fetch_recent_jobs,
    fetch_repo_dir,
    fetch_repo_file,
    fetch_repo_tree,
    fetch_tag_jobs,
)


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


def test_recent_jobs_and_runner_id():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "/projects/g%2Fr/jobs?" in str(req.url) and req.headers["PRIVATE-TOKEN"] == "tok"
        return httpx.Response(200, json=[
            {"id": 9, "name": "build", "status": "success", "runner": {"id": 3, "description": "build-01"}, "web_url": "http://gl/j/9"},
            {"id": 8, "name": "deploy", "status": "pending", "runner": None, "web_url": "http://gl/j/8"},
        ])

    jobs = fetch_recent_jobs("http://gl", "tok", "g/r", transport=_t(handler))
    assert jobs == [
        {"id": 9, "name": "build", "status": "success", "runner_id": 3, "runner_name": "build-01", "web_url": "http://gl/j/9"},
        {"id": 8, "name": "deploy", "status": "pending", "runner_id": None, "runner_name": None, "web_url": "http://gl/j/8"},
    ]
    assert fetch_recent_jobs("http://gl", "tok", "g/r", transport=_t(lambda r: httpx.Response(403))) is None


def test_job_log_head_reads_only_the_start():
    log = "Running with gitlab-runner 17.0\nPreparing the \"shell\" executor\n" + "x" * 50000

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url).endswith("/projects/g%2Fr/jobs/9/trace")
        return httpx.Response(200, content=log.encode())

    head = fetch_job_log_head("http://gl", "tok", "g/r", 9, transport=_t(handler), max_bytes=100)
    assert head is not None and len(head) == 100 and 'Preparing the "shell" executor' in head
    assert fetch_job_log_head("http://gl", "tok", "g/r", 9, transport=_t(lambda r: httpx.Response(404))) is None


def test_repo_file_without_ref_uses_default_branch():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "ref" not in req.url.params  # 브랜치를 안 적으면 GitLab 이 프로젝트 기본 브랜치(main·dev 등)
        return httpx.Response(200, text="x")

    assert fetch_repo_file("http://gl", "tok", "g/r", ".gitlab-ci.yml", transport=_t(handler)) == "x"
    assert fetch_repo_tree("http://gl", "tok", "g/r", transport=_t(lambda r: httpx.Response(200, json=[]))) == []


def test_tag_jobs_reads_pages_and_keeps_only_tag_refs():
    """빌드·배포 버전용 — 성공한 job 만(scope=success), 여러 쪽, 브랜치로 돈 job 은 뺀다."""
    pages = {
        "1": ([
            {"id": 9, "name": "deploy-prod", "ref": "prod-web-v1.2.0", "tag": True, "finished_at": "2026-10-02T01:00:00Z", "stage": "deploy"},
            {"id": 8, "name": "notify", "ref": "main", "tag": False, "finished_at": "2026-10-01T01:00:00Z"},
        ], "2"),
        "2": ([{"id": 5, "name": "build", "ref": "prod-web-v1.2.0", "tag": True, "finished_at": "2026-10-01T00:00:00Z"}], ""),
    }
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        body, nxt = pages[req.url.params["page"]]
        return httpx.Response(200, json=body, headers={"X-Next-Page": nxt})

    jobs = fetch_tag_jobs("http://gl", "tok", "g/r", transport=_t(handler))
    assert [j["id"] for j in jobs] == [9, 5]
    assert jobs[0] == {"id": 9, "name": "deploy-prod", "ref": "prod-web-v1.2.0", "finished_at": "2026-10-02T01:00:00Z"}
    assert [p["page"] for p in seen] == ["1", "2"] and all(p["scope[]"] == "success" for p in seen)
    # 쪽 수 상한 — 다음 쪽이 계속 있어도 max_pages 에서 멈춤
    endless = _t(lambda r: httpx.Response(200, json=[], headers={"X-Next-Page": "2"}))
    assert fetch_tag_jobs("http://gl", "tok", "g/r", transport=endless, max_pages=3) == []
    assert fetch_tag_jobs("http://gl", "tok", "g/r", transport=_t(lambda r: httpx.Response(401))) is None


def test_repo_dir_lists_one_folder_blobs_only():
    """버전 파일이 있는지 먼저 보려고 — 폴더 하나(재귀 X)의 파일 이름만, 쪽 넘김, 오류면 None."""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        if req.url.params["page"] == "1":
            return httpx.Response(200, json=[{"name": ".nvmrc", "type": "blob"}, {"name": "src", "type": "tree"}], headers={"X-Next-Page": "2"})
        return httpx.Response(200, json=[{"name": "package.json", "type": "blob"}])

    assert fetch_repo_dir("http://gl", "tok", "g/r", "app", "dev", transport=_t(handler)) == [".nvmrc", "package.json"]
    assert seen[0]["path"] == "app" and seen[0]["ref"] == "dev" and "recursive" not in seen[0]
    assert fetch_repo_dir("http://gl", "tok", "g/r", transport=_t(lambda r: httpx.Response(404))) is None


def test_session_reuses_one_client_per_thread():
    """부를 때마다 새로 연결(TLS)하지 않게 — 같은 스레드는 같은 Client, 다른 스레드는 따로. transport(테스트)는 그때만."""
    import threading

    import runner.gitlab as gl

    with gl._session(None, 7) as a, gl._session(None, 7) as b:
        assert a is b and not a.is_closed
    other: list = []
    t = threading.Thread(target=lambda: other.append(gl._session(None, 7).__enter__()))
    t.start()
    t.join()
    assert other[0] is not a
    with gl._session(_t(lambda r: httpx.Response(200)), 7) as c:
        assert c is not a
    assert c.is_closed  # 테스트용은 쓰고 닫음


def test_unreachable_gitlab_is_skipped_for_the_rest_of_the_run():
    """회사망에서만 받는 GitLab 을 밖(서버 수집기)에서 부르면 — 첫 접속 실패(시간 초과)만 기다리고,
    같은 수집의 남은 호출은 부르지도 않고 바로 None. 응답이 온 실패(401·404)는 접속은 된 것이라 끊김으로 안 봄."""
    import runner.gitlab as gl

    hits: list[str] = []

    def down(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.path)
        raise httpx.ConnectTimeout("timed out", request=req)

    gl.reset_down()
    try:
        assert fetch_repo_file("http://repo", "tok", "g/r", ".gitlab-ci.yml", transport=_t(down)) is None
        assert gl.is_down("http://repo/") and not gl.is_down("http://center")
        assert fetch_tag_jobs("http://repo", "tok", "g/r", transport=_t(down)) is None
        assert fetch_job_log_head("http://repo", "tok", "g/r", 5, transport=_t(down)) is None
        assert len(hits) == 1  # 두 번째부터는 기다리지 않음
        assert fetch_tag_jobs("http://center", "tok", "g/r", transport=_t(lambda r: httpx.Response(200, json=[]))) == []
        assert fetch_repo_file("http://center", "tok", "g/r", "x", transport=_t(lambda r: httpx.Response(404))) is None
        assert not gl.is_down("http://center")
    finally:
        gl.reset_down()
    assert not gl.is_down("http://repo")  # 다음 수집은 다시 붙어 봄
