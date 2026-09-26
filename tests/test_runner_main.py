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
