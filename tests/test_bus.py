import uuid

from shared.bus import actions_queue, results_queue, make_action, make_result


def test_queue_names():
    assert actions_queue("s1") == "otto.s1.actions"
    assert results_queue("s1") == "otto.s1.results"


def test_make_action():
    a = make_action("s1", "shell.exec", {"cmd": "ls"})
    assert set(a) == {"session_id", "action_id", "kind", "payload"}
    assert a["session_id"] == "s1"
    assert a["kind"] == "shell.exec"
    assert a["payload"] == {"cmd": "ls"}
    assert str(uuid.UUID(a["action_id"])) == a["action_id"]


def test_make_action_ids_are_unique():
    assert make_action("s1", "x", {})["action_id"] != make_action("s1", "x", {})["action_id"]


def test_make_result():
    a = make_action("s1", "fs.read", {"path": "x"})
    r = make_result(a, True, {"exit_code": 0})
    assert r == {
        "session_id": "s1",
        "action_id": a["action_id"],
        "kind": "fs.read.result",
        "ok": True,
        "payload": {"exit_code": 0},
    }
