from shared.models import Action, ActionKind, ActionResult, actions_queue


def test_action_roundtrip():
    a = Action(session_id="s1", kind=ActionKind.SHELL_EXEC, payload={"cmd": "ls"})
    assert Action.model_validate_json(a.model_dump_json()) == a


def test_result_names_queue():
    r = ActionResult(session_id="s1", action_id="a1", kind="shell.exec.result", ok=True)
    assert r.ok
    assert actions_queue("s1") == "actions.s1"
