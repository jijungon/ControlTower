"""서버 탭 '목록 고치기' — 운영자만 · 스위치(CT_INVENTORY_EDIT) · check-and-set · users 는 그대로.

금고는 진짜 HTTP 로 흉내 낸다(FakeVault — KV v2 의 판 번호 · cas · 정책 · LB 끊김) — CT 가 실제로 보내는
경로 · 몸통 · 금고의 거절 글자(check-and-set …)를 읽는 길까지 그대로 지나게.
"""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app import inventory_source
from app.config import settings
from tests.test_auth import _proxy, _proxy_jwt, _rsa_pair

SHOP = {
    "gw": {"host": "198.51.100.20", "port": 22, "jump": "keep-me"},
    "servers": {"api": "192.0.2.10", "worker": "192.0.2.11"},
    "users": {"dev1": {"email": "dev1@example.com", "role": "developer", "gw_account": "dev1", "server_account": "appuser"}},
    "note": "idp-login 이 적은 모르는 칸",
}


class FakeVault:
    """inventory KV v2 하나. caps = ct-inventory 정책이 허락하는 것(read · list · update · create)."""

    def __init__(self):
        self.kv: dict[str, list[dict]] = {}
        self.caps = {"read", "list", "update"}
        self.log: list[tuple[str, str, dict | None]] = []
        self.before_write = None  # CT 의 쓰기가 닿기 직전에 끼어드는 다른 쓰기(idp-login)
        self.write_fail: int | str | None = None  # 상태 코드 · "drop"(썼는데 답 없이 끊김)

    def put(self, key: str, data: dict) -> int:
        vs = self.kv.setdefault(key, [])
        vs.append({"data": copy.deepcopy(data), "created_time": f"2026-10-28T00:{len(vs):02d}:00.123456789Z"})
        return len(vs)

    def now(self, key: str) -> tuple[int, dict]:
        return len(self.kv[key]), self.kv[key][-1]["data"]

    def writes(self) -> list:
        return [x for x in self.log if x[0] == "POST" and x[1].startswith("inventory/")]


def _handler(fake: FakeVault):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 테스트 출력 조용히
            pass

        def _send(self, code: int, obj: dict) -> None:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _handle(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else None
            path = self.path.removeprefix("/v1/")
            fake.log.append((self.command, path, body))
            if path == "auth/approle/login":
                if body == {"role_id": "role-ct", "secret_id": "sid-ct"}:
                    return self._send(200, {"auth": {"client_token": "tok"}})
                return self._send(400, {"errors": ["invalid role or secret ID"]})
            if self.headers.get("X-Vault-Token") != "tok":
                return self._send(403, {"errors": ["permission denied"]})
            if self.command == "LIST" and path.startswith("inventory/metadata/"):
                env = path.removeprefix("inventory/metadata/")
                keys = [k.split("/", 1)[1] for k in fake.kv if k.startswith(env + "/")]
                return self._send(200, {"data": {"keys": keys}}) if keys else self._send(404, {"errors": []})
            if not path.startswith("inventory/data/"):
                return self._send(404, {"errors": []})
            key = path.removeprefix("inventory/data/")
            if self.command == "GET":
                if "read" not in fake.caps:
                    return self._send(403, {"errors": ["permission denied"]})
                if key not in fake.kv:
                    return self._send(404, {"errors": []})
                v, d = fake.now(key)
                meta = {"version": v, "created_time": fake.kv[key][-1]["created_time"], "custom_metadata": None}
                return self._send(200, {"data": {"data": d, "metadata": meta}})
            if self.command == "POST":
                if fake.before_write:
                    fake.before_write()
                    fake.before_write = None
                if ("update" if key in fake.kv else "create") not in fake.caps:
                    return self._send(403, {"errors": ["1 error occurred:\n\t* permission denied\n\n"]})
                if fake.write_fail and fake.write_fail != "drop":
                    return self._send(fake.write_fail, {"errors": ["upstream timed out"]})
                cas = (body.get("options") or {}).get("cas")
                cur = len(fake.kv.get(key, []))
                if cas is not None and cas != cur:
                    return self._send(400, {"errors": ["check-and-set parameter did not match the current version"]})
                v = fake.put(key, body["data"])
                if fake.write_fail == "drop":  # 금고는 썼는데 앞단이 답 없이 끊음
                    self.close_connection = True
                    self.wfile.flush()
                    self.connection.close()
                    return None
                return self._send(200, {"data": {"version": v, "created_time": fake.kv[key][-1]["created_time"]}})
            return self._send(405, {"errors": ["unsupported operation"]})

        do_GET = do_POST = do_LIST = do_PUT = do_DELETE = do_PATCH = _handle

    return H


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    fake = FakeVault()
    fake.put("dev/shop", SHOP)
    fake.put("prod/pay", {"gw": {"host": "198.51.100.30"}, "servers": {"pay-api": "192.0.2.30"}})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sid = tmp_path / "sid"
    sid.write_text("sid-ct\n")
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(settings, "ct_inventory_mode", "vault")
    monkeypatch.setattr(settings, "ct_inventory_addr", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(settings, "ct_inventory_role_id", "role-ct")
    monkeypatch.setattr(settings, "ct_inventory_secret_id_file", str(sid))
    monkeypatch.setattr(settings, "ct_inventory_edit", True)
    inventory_source.clear_cache()
    yield fake
    srv.shutdown()
    inventory_source.clear_cache()


def _as(monkeypatch, groups, email="ops@example.com"):
    priv, pub = _rsa_pair()
    _proxy(monkeypatch, pub)
    return {"X-authentik-jwt": _proxy_jwt(priv, groups=groups, email=email)}


def _body(**over):
    b = {"version": 1, "gw": {"host": "198.51.100.20", "port": 22}, "servers": dict(SHOP["servers"])}
    b.update(over)
    return b


URL = "/api/inventory/dev/shop"


def _three(client, h, body=None):
    body = body or _body()
    return [client.get(URL, headers=h), client.post(URL + "/preview", json=body, headers=h),
            client.put(URL, json=body, headers=h)]


# ── 스위치 · 누가 ──

def test_스위치가_꺼져_있으면_운영자도_403_꺼져_있음_금고는_안_건드린다(client, monkeypatch, vault):
    monkeypatch.setattr(settings, "ct_inventory_edit", False)
    h = _as(monkeypatch, ["server-admin"])
    for r in _three(client, h):
        assert r.status_code == 403 and "꺼져 있어요" in r.json()["detail"]
    assert vault.log == []
    a = client.get("/api/access", headers=h).json()
    assert a["state"] == "ok" and a["can_edit"] is False


def test_개발자는_중간_문지기가_먼저_403_금고는_안_건드린다(client, monkeypatch, vault):
    h = _as(monkeypatch, ["developer"])
    for r in _three(client, h):
        assert r.status_code == 403 and r.json() == {"detail": "개발자는 서버 탭만 볼 수 있어요"}
    assert vault.log == []
    assert client.get("/api/access", headers=h).json()["can_edit"] is False


def test_viewer_는_403_몸통이_틀려도_422_가_아니라_403(client, monkeypatch, vault):
    h = _as(monkeypatch, ["viewer"])
    for r in _three(client, h):
        assert r.status_code == 403 and "운영자(server-admin)만" in r.json()["detail"]
    r = client.put(URL, json={"nonsense": True}, headers=h)
    assert r.status_code == 403
    assert vault.log == []


def test_누군지_모르면_403_proxy_신분증_없음_흉내_none_모드(client, monkeypatch, vault):
    _, pub = _rsa_pair()
    forged, _ = _rsa_pair()
    _proxy(monkeypatch, pub)
    for h in ({}, {"X-authentik-email": "ops@example.com", "X-authentik-groups": "server-admin"},
              {"X-authentik-jwt": _proxy_jwt(forged, groups=["server-admin"])}):
        for r in _three(client, h):
            assert r.status_code == 403 and "누군지 몰라요" in r.json()["detail"], h
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", False)
    for r in _three(client, {}):
        assert r.status_code == 403 and "누군지 몰라요" in r.json()["detail"]
    assert vault.log == []


def test_로컬_미리보기만_로그인_없이_고친다(client, monkeypatch, vault):
    monkeypatch.setattr(settings, "ct_auth_mode", "none")
    monkeypatch.setattr(settings, "ct_access_local_preview", True)
    assert client.get(URL).status_code == 200
    r = client.put(URL, json=_body(servers={**SHOP["servers"], "api-2": "192.0.2.12"}))
    assert r.status_code == 200
    assert client.get("/api/audit").json()[0]["actor"] == "로컬 미리보기(로그인 없음)"


def test_운영자는_고치고_개발자와_운영자_둘_다인_사람도(client, monkeypatch, vault):
    for groups in (["server-admin"], ["developer", "server-admin"]):
        h = _as(monkeypatch, groups)
        r = client.get(URL, headers=h)
        assert r.status_code == 200, groups
        assert client.get("/api/access", headers=h).json()["can_edit"] is True


def test_금고_연결이_꺼져_있으면_409(client, monkeypatch, vault):
    monkeypatch.setattr(settings, "ct_inventory_mode", "off")
    r = client.get(URL, headers=_as(monkeypatch, ["server-admin"]))
    assert r.status_code == 409 and "연결 전" in r.json()["detail"]
    assert vault.log == []


# ── 읽기 · 저장 ──

def test_읽기는_캐시_없이_판_번호와_서버_users_는_몇_명만(client, monkeypatch, vault):
    r = client.get(URL, headers=_as(monkeypatch, ["server-admin"])).json()
    assert r == {
        "env": "dev", "service": "shop", "version": 1, "updated_at": "2026-10-28T00:00:00.123456789Z",
        "last_edit": {"here": False, "by": None, "at": None},
        "gw": {"host": "198.51.100.20", "port": 22}, "servers": SHOP["servers"], "users_count": 1,
    }
    assert "dev1@example.com" not in json.dumps(r)


def test_저장은_cas_통째_쓰기_users_와_모르는_칸은_그대로(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    body = _body(gw={"host": "198.51.100.21", "port": 2222},
                 servers={"api": "192.0.2.99", "api-2": "192.0.2.12"},  # worker 빼고 api 주소 바꾸고 api-2 추가
                 users={"evil": {"email": "x@example.com"}})  # 몸통에 users 를 넣어도 무시
    r = client.put(URL, json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["saved"] is True and r.json()["version"] == 2
    (_, path, sent), = vault.writes()
    assert path == "inventory/data/dev/shop" and sent["options"] == {"cas": 1}
    v, now = vault.now("dev/shop")
    assert v == 2
    assert now["users"] == SHOP["users"], "users 를 건드렸다"
    assert now["note"] == SHOP["note"] and now["gw"]["jump"] == "keep-me", "모르는 칸을 잃었다"
    assert now["gw"] == {"host": "198.51.100.21", "port": 2222, "jump": "keep-me"}
    assert now["servers"] == {"api": "192.0.2.99", "api-2": "192.0.2.12"}
    assert set(now) == set(SHOP), "칸을 더하거나 뺐다(반쪽짜리 · 덧붙임 없이 통째)"


def test_작업이력에_누가_무엇을_남기고_주소는_안_적는다_지금_판을_누가_썼나(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"], email="ops@example.com")
    body = _body(servers={"api": "192.0.2.10", "worker-1": "192.0.2.11", "api-2": "192.0.2.12"})
    assert client.put(URL, json=body, headers=h).status_code == 200
    row = client.get("/api/audit", headers=h).json()[0]
    assert (row["action"], row["actor"], row["target_type"], row["target_id"]) == (
        "inventory.edit", "ops@example.com", "inventory", "dev/shop")
    assert row["detail"] == "v1 → v2 · 서버 이름 바뀜 worker → worker-1 · 서버 추가 api-2"
    assert "192.0.2" not in row["detail"] and "198.51.100" not in row["detail"]
    last = client.get(URL, headers=h).json()["last_edit"]
    assert last["here"] is True and last["by"] == "ops@example.com"
    vault.put("dev/shop", {**vault.now("dev/shop")[1], "servers": {}})  # 그 뒤 idp-login 이 고침
    assert client.get(URL, headers=h).json()["last_edit"] == {"here": False, "by": None, "at": None}


def test_저장하면_누가_어디로_가_바로_새_목록(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    assert "api-2" not in json.dumps(client.get("/api/access", headers=h).json())  # 캐시에 담김
    client.put(URL, json=_body(servers={**SHOP["servers"], "api-2": "192.0.2.12"}), headers=h)
    assert "api-2" in json.dumps(client.get("/api/access", headers=h).json())


def test_확인은_바뀌는_것만_보여주고_쓰지_않는다(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    body = _body(gw={"host": "198.51.100.20", "port": 2222}, servers={"api": "192.0.2.99", "new": "192.0.2.13"})
    r = client.post(URL + "/preview", json=body, headers=h).json()
    assert r["version"] == 1
    assert r["changes"] == [
        {"kind": "gw_port", "from": 22, "to": 2222},
        {"kind": "server_remove", "name": "worker", "from": "192.0.2.11"},
        {"kind": "server_add", "name": "new", "to": "192.0.2.13"},
        {"kind": "server_addr", "name": "api", "from": "192.0.2.10", "to": "192.0.2.99"},
    ]
    assert vault.writes() == [] and vault.now("dev/shop")[0] == 1


def test_바뀐_게_없으면_400_쓰지_않는다(client, monkeypatch, vault):
    r = client.put(URL, json=_body(), headers=_as(monkeypatch, ["server-admin"]))
    assert r.status_code == 400 and "바뀐 게 없어요" in r.json()["detail"]
    assert vault.writes() == []


def test_포트_22_는_없던_칸을_만들지_않고_글자로_적힌_포트는_글자로(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    vault.put("prod/pay", {"gw": {"host": "198.51.100.30", "port": "2200"}, "servers": {"pay-api": "192.0.2.30"}})
    body = {"version": 2, "gw": {"host": "198.51.100.30", "port": 2201}, "servers": {"pay-api": "192.0.2.30"}}
    assert client.put("/api/inventory/prod/pay", json=body, headers=h).status_code == 200
    assert vault.now("prod/pay")[1]["gw"] == {"host": "198.51.100.30", "port": "2201"}
    vault.put("prod/pay", {"gw": {"host": "198.51.100.30"}, "servers": {"pay-api": "192.0.2.30"}})
    body = {"version": 4, "gw": {"host": "198.51.100.30", "port": 22}, "servers": {"pay-api": "192.0.2.31"}}
    assert client.put("/api/inventory/prod/pay", json=body, headers=h).status_code == 200
    assert vault.now("prod/pay")[1]["gw"] == {"host": "198.51.100.30"}


# ── 같은 때 idp-login 이 쓰면 ──

def test_고치는_사이_판이_바뀌었으면_쓰기_전에_409(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    vault.put("dev/shop", {**SHOP, "servers": {**SHOP["servers"], "batch": "192.0.2.14"}})  # idp-login server add
    r = client.put(URL, json=_body(servers={"api": "192.0.2.10"}), headers=h)  # 화면은 v1 을 보고 고침
    assert r.status_code == 409 and "다시 불러온 뒤 고쳐 주세요" in r.json()["detail"]
    assert vault.writes() == []
    assert vault.now("dev/shop")[1]["servers"]["batch"] == "192.0.2.14"


def test_읽고_쓰는_그_틈에_끼어들면_금고의_cas_가_막고_409(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    vault.before_write = lambda: vault.put("dev/shop", {**SHOP, "users": {}})  # 틈에 idp-login 이 씀
    r = client.put(URL, json=_body(servers={"api": "192.0.2.10"}), headers=h)
    assert r.status_code == 409 and "다시 불러온 뒤 고쳐 주세요" in r.json()["detail"]
    v, now = vault.now("dev/shop")
    assert v == 2 and now["servers"] == SHOP["servers"], "CT 가 idp-login 의 쓰기를 덮었다"
    assert [x["action"] for x in client.get("/api/audit", headers=h).json()] == []


# ── 금고가 거절 · 답이 없음 ──

def test_정책에_쓰기가_없으면_금고가_거절_할_일을_앞에_금고_답은_작은_줄로_아무것도_안_바뀜(client, monkeypatch, vault):
    """prod · 새 항목처럼 정책이 update 를 허락하지 않으면 금고가 403 — 'permission denied' 만으론 할 일을 모른다."""
    vault.caps = {"read", "list"}  # 정책에 쓰기가 없는 곳(prod 등)
    h = _as(monkeypatch, ["server-admin"])
    r = client.put(URL, json=_body(servers={"api": "192.0.2.10"}), headers=h)
    assert r.status_code == 502
    d = r.json()["detail"]
    assert d["message"] == "금고가 거절했어요 — prod 나 새 서비스는 gw 에서 idp-login 으로(service add 등) 고쳐요"
    assert "permission denied" not in d["message"]
    assert "아무것도 안 바뀌었어요" in d["why"] and "HTTP 403" in d["why"] and "permission denied" in d["why"]
    assert vault.now("dev/shop")[0] == 1
    assert client.get("/api/audit", headers=h).json() == []


def test_403_이_아닌_거절은_예전처럼_까닭_그대로(client, monkeypatch, vault):
    vault.write_fail = 400  # 금고가 다른 까닭으로 거절(4xx) — 아무것도 안 씀
    h = _as(monkeypatch, ["server-admin"])
    r = client.put(URL, json=_body(servers={"api": "192.0.2.10"}), headers=h)
    d = r.json()["detail"]
    assert r.status_code == 502 and isinstance(d, str)
    assert "거절했어요(아무것도 안 바뀜)" in d and "HTTP 400" in d


@pytest.mark.parametrize("fail", [504, "drop"])
def test_답을_못_받으면_됐다고도_안_됐다고도_안_하고_모름(client, monkeypatch, vault, fail):
    vault.write_fail = fail
    h = _as(monkeypatch, ["server-admin"])
    r = client.put(URL, json=_body(servers={"api": "192.0.2.10"}), headers=h)
    assert r.status_code == 502 and r.json()["detail"].startswith("저장됐는지 모름 — 다시 불러와 확인해 주세요")
    row = client.get("/api/audit", headers=h).json()[0]
    assert row["action"] == "inventory.edit_unknown" and row["detail"].startswith("v1 → ? · 서버 뺌 worker")


def test_금고에_로그인_못_하면_502_아무것도_안_바뀜(client, monkeypatch, vault, tmp_path):
    bad = tmp_path / "bad"
    bad.write_text("wrong")
    monkeypatch.setattr(settings, "ct_inventory_secret_id_file", str(bad))
    r = client.put(URL, json=_body(servers={}), headers=_as(monkeypatch, ["server-admin"]))
    assert r.status_code == 502 and "아무것도 안 바뀜" in r.json()["detail"]
    assert vault.writes() == []


# ── 모양 검사 ──

@pytest.mark.parametrize("servers", [
    {"-oProxyCommand=x": "192.0.2.1"}, {"..": "192.0.2.1"}, {"a b": "192.0.2.1"},
    {"api": "-oProxyCommand=x"}, {"api": "192.0.2.1; rm"}, {"api": ""},
])
def test_이름_주소_모양이_이상하면_422_금고에_안_간다(client, monkeypatch, vault, servers):
    r = client.put(URL, json=_body(servers=servers), headers=_as(monkeypatch, ["server-admin"]))
    assert r.status_code == 422 and "모양이 이상해요" in r.json()["detail"]
    assert vault.log == []


def test_gw_포트_범위와_주소(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    assert client.put(URL, json=_body(gw={"host": "198.51.100.20", "port": 0}), headers=h).status_code == 422
    assert client.put(URL, json=_body(gw={"host": "-x", "port": 22}), headers=h).status_code == 422


def test_없는_환경_서비스는_404_새_서비스는_idp_login_으로(client, monkeypatch, vault):
    h = _as(monkeypatch, ["server-admin"])
    assert client.get("/api/inventory/qa/shop", headers=h).status_code == 404
    r = client.get("/api/inventory/dev/nope", headers=h)
    assert r.status_code == 404 and "idp-login service add" in r.json()["detail"]
    assert client.put("/api/inventory/dev/nope", json=_body(), headers=h).status_code == 404
    assert vault.writes() == [], "없는 서비스를 만들었다(create 는 안 쓴다)"


def test_servers_모양이_예상과_다르면_고치지_않는다(client, monkeypatch, vault):
    vault.put("dev/shop", {**SHOP, "servers": ["api", "worker"]})
    r = client.get(URL, headers=_as(monkeypatch, ["server-admin"]))
    assert r.status_code == 409 and "모양이 예상과 달라" in r.json()["detail"]


def test_금고에_하는_일은_항목_읽기와_cas_쓰기뿐(client, monkeypatch, vault):
    """7단계 정책의 근거: inventory/data/<환경>/<서비스> 의 GET(read) · POST(update) 만. metadata 쓰기 · DELETE · create 없음."""
    h = _as(monkeypatch, ["server-admin"])
    client.get(URL, headers=h)
    client.post(URL + "/preview", json=_body(servers={}), headers=h)
    client.put(URL, json=_body(servers={}), headers=h)
    used = {(m, p) for m, p, _ in vault.log}
    assert used == {("POST", "auth/approle/login"), ("GET", "inventory/data/dev/shop"), ("POST", "inventory/data/dev/shop")}
    assert all(b["options"]["cas"] >= 1 for _, _, b in vault.writes()), "cas 없이 썼다"
