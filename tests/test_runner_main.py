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
