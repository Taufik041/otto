import pytest

from shared import config, db as shared_db
from shared.bus import results_queue
from shared.events import append_event, load_events
from shared.sessions import create_session, get_session
from brain import main as brain_main
from tests.fakes import FakeChannel, FakeConnection, auto_reply, llm_tool_calls, llm_final, use_env
from tests.test_brain_loop import fake_client


@pytest.fixture
def fake_bus(monkeypatch):
    async def connect(url):
        # a fresh channel per run: each main() call has its own event loop
        ch = FakeChannel()
        auto_reply(ch, ch.queue(results_queue(config.SESSION_ID)))
        return FakeConnection(ch)

    monkeypatch.setattr(brain_main, "connect", connect)


@pytest.fixture
def no_bus(monkeypatch):
    async def connect(url):
        raise AssertionError("should not touch the bus")
    monkeypatch.setattr(brain_main, "connect", connect)


def test_new_session(monkeypatch, fake_bus):
    fake_client(monkeypatch, [llm_tool_calls(("git_status", {})), llm_final("done")])
    brain_main.main(["fix", "the", "bug"])
    row = get_session(config.SESSION_ID)
    assert (row.task, row.status) == ("fix the bug", "done")


def test_new_session_needs_an_available_model(monkeypatch, no_bus):
    use_env(monkeypatch, {})  # no provider keys
    with pytest.raises(SystemExit) as e:
        brain_main.main(["fix it"])
    assert "no LLM model is available" in str(e.value.code) and "OPENROUTER_API_KEY" in str(e.value.code)
    assert get_session(config.SESSION_ID) is None


def test_existing_session_is_refused_without_force_new(no_bus, capsys):
    create_session(config.SESSION_ID, task="old", repo_url=None, model="m")
    with pytest.raises(SystemExit) as e:
        brain_main.main(["new task"])
    assert "--force-new" in str(e.value.code) and "--resume" in str(e.value.code)
    assert get_session(config.SESSION_ID).task == "old"


def test_force_new_discards_the_old_session(monkeypatch, fake_bus):
    sid = config.SESSION_ID
    create_session(sid, task="old", repo_url=None, model="m")
    for _ in range(5):
        append_event(sid, "x", {})
    fake_client(monkeypatch, [llm_final("done")])

    brain_main.main(["--force-new", "new task"])

    assert get_session(sid).task == "new task"
    evs = load_events(sid)
    assert evs[0].seq == 1 and evs[0].type == "session.created"
    assert "x" not in [e.type for e in evs]


def test_resume_continues_the_same_session(monkeypatch, fake_bus):
    fake_client(monkeypatch, [llm_final("hello")])
    brain_main.main(["say hi"])
    n = len(load_events(config.SESSION_ID))

    calls, _ = fake_client(monkeypatch, [llm_final("I said hello")])
    brain_main.main(["--resume", "what", "did you say?"])

    evs = load_events(config.SESSION_ID)
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))
    assert evs[n].payload == {"message": {"role": "user", "content": "what did you say?"}}
    assert calls[0][-2:] == [{"role": "assistant", "content": "hello"},
                             {"role": "user", "content": "what did you say?"}]


def test_resume_without_a_session_fails(no_bus):
    with pytest.raises(SystemExit) as e:
        brain_main.main(["--resume", "hi"])
    assert "no session" in str(e.value.code)


def test_show_prints_row_and_timeline(monkeypatch, fake_bus, capsys):
    fake_client(monkeypatch, [llm_tool_calls(("fs_read", {"path": "a.py"})), llm_final("all\ngood")])
    brain_main.main(["read a.py"])
    capsys.readouterr()
    monkeypatch.setattr(brain_main, "connect", None)  # --show must not touch the bus

    brain_main.main(["--show"])

    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"session {config.SESSION_ID}") and "status=done" in out[0]
    assert any("read a.py" in l for l in out[:4])
    timeline = [l for l in out if l.lstrip()[:1].isdigit()]
    assert len(timeline) == len(load_events(config.SESSION_ID))
    assert "session.created" in timeline[0]
    assert any("bus.action" in l and "fs.read" in l for l in timeline)
    assert any("llm.message" in l and "fs_read" in l for l in timeline)
    assert "all good" in timeline[-2]  # one line per event
    assert "done" in timeline[-1]


def test_show_without_a_session(no_bus, capsys):
    brain_main.main(["--show"])
    assert "no session" in capsys.readouterr().out


def test_unreachable_database_fails_loudly(monkeypatch, no_bus):
    monkeypatch.setattr(shared_db, "_engine", None)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://otto:hunter2@127.0.0.1:1/otto")
    with pytest.raises(SystemExit) as e:
        brain_main.main(["a task"])
    msg = str(e.value.code)
    assert "cannot reach the database" in msg and "127.0.0.1:1" in msg
    assert "hunter2" not in msg


def test_task_is_required(no_bus):
    with pytest.raises(SystemExit) as e:
        brain_main.main([])
    assert e.value.code == 2
