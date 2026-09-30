"""Each user sees only their own sessions: over HTTP and over the WebSocket."""
import pytest
from starlette.websockets import WebSocketDisconnect

from shared.sessions import create_session, get_session
from tests.conftest import ORIGIN
from tests.fakes import log_in_as, signup

REPO = "Taufik041/otto_test"
SID = "aaaa000001"


@pytest.fixture
def users(client):
    """Users A and B; A owns session SID. The client is signed in as B."""
    a = signup(client, email="a@example.com")["id"]
    client.cookies.clear()
    b = signup(client, email="b@example.com")["id"]
    create_session(SID, task="A's secret task", repo=REPO, model="m", status="done", user_id=a)
    return a, b


def ws(client, sid=SID, origin=ORIGIN):
    return client.websocket_connect(f"/sessions/{sid}/ws", headers={"origin": origin} if origin else {})


def close_code(client, **kw) -> int:
    with pytest.raises(WebSocketDisconnect) as e:
        with ws(client, **kw) as s:
            s.receive_json()
    return e.value.code


def test_another_users_session_is_404_everywhere(client, users, env):
    assert client.get(f"/sessions/{SID}").status_code == 404
    assert client.get(f"/sessions/{SID}/events").status_code == 404
    assert client.post(f"/sessions/{SID}/messages", json={"text": "hi"}).status_code == 404
    assert client.delete(f"/sessions/{SID}").status_code == 404
    assert client.post(f"/sessions/{SID}/stop").status_code == 404
    assert client.patch(f"/sessions/{SID}", json={"title": "mine now"}).status_code == 404
    assert "secret" not in client.get("/sessions").text
    assert env[1].calls == []
    assert get_session(SID).status == "done"


def test_each_user_lists_only_their_own_sessions(client, users):
    a, b = users
    create_session("bbbb000001", task="B's task", repo=REPO, model="m", user_id=b)
    create_session("cli0000001", task="from the CLI", repo=REPO, model="m")  # no owner
    assert [s["id"] for s in client.get("/sessions").json()] == ["bbbb000001"]
    log_in_as(client, a)
    assert [s["id"] for s in client.get("/sessions").json()] == [SID]


def test_the_owner_can_read_their_session(client, users):
    log_in_as(client, users[0])
    assert client.get(f"/sessions/{SID}").status_code == 200
    assert client.get(f"/sessions/{SID}/events").json()[0]["payload"]["task"] == "A's secret task"


def test_session_routes_need_a_login(client, users):
    client.cookies.clear()
    for method, path in [("get", "/sessions"), ("get", f"/sessions/{SID}"), ("get", f"/sessions/{SID}/events"),
                         ("post", f"/sessions/{SID}/messages"), ("delete", f"/sessions/{SID}")]:
        r = getattr(client, method)(path, **({"json": {"text": "x"}} if method == "post" else {}))
        assert r.status_code == 401, (method, path)
    assert client.post("/sessions", json={"repo": REPO, "message": "t"}).status_code == 401
    assert client.patch(f"/sessions/{SID}", json={"title": "x"}).status_code == 401


def test_the_owner_can_open_the_websocket(client, users):
    log_in_as(client, users[0])
    with ws(client) as s:
        assert s.receive_json()["type"] == "session.created"


def test_another_users_websocket_is_closed_with_4404(client, users):
    assert close_code(client) == 4404


def test_the_websocket_needs_a_login(client, users):
    client.cookies.clear()
    assert close_code(client) == 4401


@pytest.mark.parametrize("origin", ["http://evil.example", "null", None])
def test_the_websocket_checks_the_origin(client, users, origin):
    log_in_as(client, users[0])
    assert close_code(client, origin=origin) == 4403
