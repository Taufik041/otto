import pytest

from shared import config
from shared.bus import actions_queue, results_queue, make_action
from runner import main as runner_main
from tests.fakes import FakeChannel, FakeConnection


@pytest.fixture
def ch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE", str(tmp_path))
    monkeypatch.setattr(config, "SESSION_ID", "s1")
    ch = FakeChannel()

    async def fake_connect(url):
        return FakeConnection(ch)

    monkeypatch.setattr(runner_main, "connect_robust", fake_connect)
    return ch


@pytest.mark.asyncio
async def test_bad_messages_are_acked_and_skipped(ch):
    q = ch.queue(actions_queue("s1"))
    bad = [q.put(b"not json {"), q.put(b"\xff\xfe"), q.put(b"[1, 2]")]
    good = q.put(make_action("s1", "shell.exec", {"cmd": "echo hi"}))
    q.close()

    await runner_main.main()  # returns once the fake queue is drained

    assert all(m.acked and not m.rejected for m in bad)
    assert good.acked
    [(key, result)] = ch.default_exchange.published
    assert key == results_queue("s1")
    assert result["ok"] is True
    assert result["payload"]["stdout"] == "hi\n"


def flaky_connect(ch, failures):
    calls = []

    async def connect(url):
        calls.append(url)
        if len(calls) <= failures:
            raise ConnectionError("broker not up yet")
        return FakeConnection(ch)

    return connect, calls


@pytest.mark.asyncio
async def test_connect_retries_until_broker_is_up(ch, monkeypatch, capsys):
    connect, calls = flaky_connect(ch, failures=2)
    monkeypatch.setattr(runner_main, "connect_robust", connect)
    monkeypatch.setattr(runner_main, "CONNECT_DELAY", 0)
    ch.queue(actions_queue("s1")).close()

    await runner_main.main()

    assert len(calls) == 3
    assert capsys.readouterr().out.count("broker not up yet") == 2


@pytest.mark.asyncio
async def test_connect_gives_up_with_clear_error(ch, monkeypatch):
    connect, calls = flaky_connect(ch, failures=10**6)
    monkeypatch.setattr(runner_main, "connect_robust", connect)
    monkeypatch.setattr(runner_main, "CONNECT_DELAY", 0)

    with pytest.raises(RuntimeError, match="could not connect to the bus"):
        await runner_main.main()
    assert len(calls) == runner_main.CONNECT_ATTEMPTS


def test_connect_retry_window_is_about_60s():
    assert runner_main.CONNECT_ATTEMPTS * runner_main.CONNECT_DELAY == 60


# --- control actions and idle exit ------------------------------------------------

import asyncio


@pytest.fixture
def conn(ch, monkeypatch):
    c = FakeConnection(ch)

    async def connect(url):
        return c

    monkeypatch.setattr(runner_main, "connect_robust", connect)
    return c


def results(ch):
    return [r for _, r in ch.default_exchange.published]


@pytest.mark.asyncio
async def test_ping_replies_pong_and_keeps_serving(ch, conn):
    q = ch.queue(actions_queue("s1"))
    q.put(make_action("s1", "control.ping", {}))
    q.put(make_action("s1", "shell.exec", {"cmd": "echo hi"}))
    q.close()

    await runner_main.main()

    ping, echo = results(ch)
    assert ping["ok"] is True and ping["payload"]["pong"] is True
    assert ping["kind"] == "control.ping.result"
    assert echo["payload"]["stdout"] == "hi\n"


@pytest.mark.asyncio
async def test_shutdown_replies_then_exits(ch, conn, capsys):
    q = ch.queue(actions_queue("s1"))
    stop = q.put(make_action("s1", "control.shutdown", {}))
    later = q.put(make_action("s1", "shell.exec", {"cmd": "echo never"}))
    # no q.close(): only the shutdown can end the loop

    await asyncio.wait_for(runner_main.main(), 2)

    [r] = results(ch)
    assert r["ok"] is True and r["kind"] == "control.shutdown.result"
    assert stop.acked and not later.acked
    assert conn.closed
    assert "shutdown" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_idle_timeout_exits(ch, conn, monkeypatch, capsys):
    monkeypatch.setattr(config, "SANDBOX_IDLE_MINUTES", 0.1 / 60)  # 100 ms
    q = ch.queue(actions_queue("s1"))

    async def trickle():
        # one action every 50 ms keeps the runner alive past its 100 ms idle limit
        for i in range(4):
            await asyncio.sleep(0.05)
            q.put(make_action("s1", "shell.exec", {"cmd": f"echo {i}"}))

    feeder = asyncio.ensure_future(trickle())
    t0 = asyncio.get_running_loop().time()
    await asyncio.wait_for(runner_main.main(), 2)
    elapsed = asyncio.get_running_loop().time() - t0
    await feeder

    assert [r["payload"]["stdout"] for r in results(ch)] == ["0\n", "1\n", "2\n", "3\n"]
    assert elapsed >= 0.25
    assert conn.closed
    assert "idle" in capsys.readouterr().out
