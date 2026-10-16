"""CI awareness, the shared part (shared/ci.py): a session's pushed head SHA gets the CI results
for that SHA as ci.updated snapshots, which never move backwards on a late or repeated update."""
from datetime import timedelta

import pytest

from shared import ci
from shared.events import append_event, load_events
from shared.models import utcnow
from shared.sessions import (
    attention,
    create_session,
    get_session,
    mark_seen,
    set_status,
)

SHA = "a" * 40
T0 = utcnow().replace(microsecond=0)


def at(seconds) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def run(id=1, name="tests", status="completed", conclusion="success", started=10, completed=70, actions=True, **kw):
    """A check run as GitHub's API and webhooks give it."""
    return {"id": id, "name": name, "head_sha": SHA, "status": status, "conclusion": conclusion,
            "started_at": at(started) if started is not None else None,
            "completed_at": at(completed) if completed is not None and status == "completed" else None,
            "html_url": f"https://github.com/o/r/actions/runs/9/job/{id}",
            "app": {"slug": "github-actions" if actions else "other-ci"}, **kw}


def status(context="deploy/preview", state="success", updated=30, url="https://ci.example/1"):
    """A commit status as the status webhook and the combined-status API give it."""
    return {"context": context, "state": state, "target_url": url, "description": f"{context}: {state}",
            "created_at": at(updated), "updated_at": at(updated)}


def session(sid="s1", repo="Taufik041/otto_test"):
    create_session(sid, task="fix it", repo=repo, model="m", status="done")
    return sid


def snapshots(sid):
    return [e.payload for e in load_events(sid) if e.type == "ci.updated"]


# --- normalizing ---------------------------------------------------------------------------------

def test_a_check_run_becomes_a_check_with_its_duration():
    c = ci.from_check_run(run(conclusion="failure", started=10, completed=75))
    assert c == {"key": "run:1", "name": "tests", "status": "completed", "conclusion": "failure",
                 "started_at": at(10), "completed_at": at(75), "duration": 65,
                 "html_url": "https://github.com/o/r/actions/runs/9/job/1", "job_id": 1, "updated": at(75)}


def test_only_an_actions_check_run_has_a_job_for_its_logs():
    assert ci.from_check_run(run(actions=False))["job_id"] is None


def test_a_commit_status_becomes_a_check():
    assert ci.from_status(status(state="pending")) == {
        "key": "status:deploy/preview", "name": "deploy/preview", "status": "in_progress", "conclusion": None,
        "started_at": at(30), "completed_at": None, "duration": None, "html_url": "https://ci.example/1",
        "job_id": None, "updated": at(30)}
    assert ci.from_status(status(state="error"))["conclusion"] == "failure"
    assert ci.from_status(status(state="success"))["status"] == "completed"


# --- the overall state -----------------------------------------------------------------------------

@pytest.mark.parametrize("checks, want", [
    ([run(status="queued", conclusion=None, completed=None)], "queued"),
    ([run(status="in_progress", conclusion=None, completed=None)], "running"),
    ([run(), run(id=2, name="lint", status="queued", conclusion=None, completed=None)], "running"),
    ([run(), run(id=2, name="lint")], "passed"),
    ([run(), run(id=2, name="lint", conclusion="skipped"), run(id=3, name="x", conclusion="neutral")], "passed"),
    ([run(), run(id=2, name="lint", conclusion="failure")], "failed"),
    ([run(), run(id=2, name="lint", conclusion="timed_out")], "failed"),
    ([run(conclusion="cancelled"), run(id=2, name="lint")], "cancelled"),
    ([run(conclusion="cancelled"), run(id=2, name="lint", conclusion="failure")], "failed"),
])
def test_the_overall_state(checks, want):
    assert ci.overall([ci.from_check_run(c) for c in checks], pushed_at=T0, now=T0) == want


def test_no_checks_is_queued_for_three_minutes_then_none():
    assert ci.overall([], pushed_at=T0, now=T0 + timedelta(seconds=179)) == "queued"
    assert ci.overall([], pushed_at=T0, now=T0 + timedelta(seconds=180)) == "none"


# --- mapping a SHA to its session -------------------------------------------------------------------

def test_a_push_resets_ci_for_the_new_sha():
    sid = session()
    assert ci.pushed(sid, SHA, now=T0) is True
    assert get_session(sid).head_sha == SHA
    [snap] = snapshots(sid)
    assert snap == {"sha": SHA, "state": "queued", "checks": [], "url": None, "pushed_at": at(0)}


def test_the_same_push_twice_records_one_reset():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    assert ci.pushed(sid, SHA, now=T0) is False
    assert len(snapshots(sid)) == 1


def test_events_map_to_the_session_whose_pushed_head_is_that_sha():
    sid = session()
    other = session("s2")
    ci.pushed(sid, SHA, now=T0)
    ci.pushed(other, "b" * 40, now=T0)
    assert [s.id for s in ci.sessions_for("taufik041/OTTO_TEST", SHA)] == [sid]  # any case
    assert ci.sessions_for("Taufik041/elsewhere", SHA) == []
    assert ci.sessions_for("Taufik041/otto_test", "c" * 40) == []


def test_a_new_push_moves_the_session_to_the_new_sha_and_old_events_no_longer_map():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run(conclusion="failure"))], now=T0)
    ci.pushed(sid, "b" * 40, now=T0 + timedelta(minutes=5))
    assert ci.sessions_for("Taufik041/otto_test", SHA) == []
    assert ci.latest(sid) == {"sha": "b" * 40, "state": "queued", "checks": [], "url": None, "pushed_at": at(300)}


# --- recording ---------------------------------------------------------------------------------------

def test_record_merges_checks_and_stores_a_snapshot_only_when_something_changed():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    first = ci.record(sid, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))], now=T0)
    assert first["state"] == "running"
    assert ci.record(sid, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))], now=T0) is None
    done = ci.record(sid, SHA, [ci.from_check_run(run())], now=T0)
    assert done["state"] == "passed" and [c["conclusion"] for c in done["checks"]] == ["success"]
    assert [s["state"] for s in snapshots(sid)] == ["queued", "running", "passed"]


def test_a_late_in_progress_never_moves_a_completed_check_backwards():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run(conclusion="failure"))], now=T0)
    assert ci.record(sid, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))],
                     now=T0) is None
    assert ci.record(sid, SHA, [ci.from_check_run(run(status="queued", conclusion=None, started=0, completed=None))],
                     now=T0) is None
    assert ci.latest(sid)["state"] == "failed"


def test_an_older_commit_status_never_replaces_a_newer_one():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_status(status(state="success", updated=60))], now=T0)
    assert ci.record(sid, SHA, [ci.from_status(status(state="pending", updated=20))], now=T0) is None
    assert ci.latest(sid)["state"] == "passed"
    # a newer one does: the status was set again (a rerun)
    assert ci.record(sid, SHA, [ci.from_status(status(state="pending", updated=90))], now=T0)["state"] == "running"


def test_a_rerun_of_a_check_replaces_the_old_run_by_name():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run(id=1, conclusion="failure", started=10, completed=40))], now=T0)
    snap = ci.record(sid, SHA, [ci.from_check_run(run(id=2, status="in_progress", conclusion=None, started=100,
                                                      completed=None))], now=T0)
    assert snap["state"] == "running" and [c["key"] for c in snap["checks"]] == ["run:2"]
    # the old run's late update doesn't bring it back
    assert ci.record(sid, SHA, [ci.from_check_run(run(id=1, conclusion="failure", started=10, completed=41))],
                     now=T0) is None


def test_record_for_a_sha_that_is_no_longer_the_head_is_ignored():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.pushed(sid, "b" * 40, now=T0)
    assert ci.record(sid, SHA, [ci.from_check_run(run())], now=T0) is None
    assert ci.latest(sid)["sha"] == "b" * 40


def test_record_without_a_reset_starts_from_nothing():
    """A push the brain didn't announce (an older worker): the first CI news starts the snapshot."""
    sid = session()
    from shared.db import get_db
    from shared.models import Session

    with get_db() as s:
        row = s.get(Session, sid)
        row.head_sha = SHA
        s.add(row)
    snap = ci.record(sid, SHA, [ci.from_check_run(run())], now=T0)
    assert snap["sha"] == SHA and snap["state"] == "passed" and snap["pushed_at"] == at(0)


def test_the_link_is_the_first_failing_check_else_the_workflow_run_else_the_first_check():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    snap = ci.record(sid, SHA, [ci.from_check_run(run(id=1))], now=T0)
    assert snap["url"] == "https://github.com/o/r/actions/runs/9/job/1"
    snap = ci.record(sid, SHA, [], run_url="https://github.com/o/r/actions/runs/9", now=T0)
    assert snap["url"] == "https://github.com/o/r/actions/runs/9"
    snap = ci.record(sid, SHA, [ci.from_check_run(run(id=2, name="lint", conclusion="failure"))], now=T0)
    assert snap["url"] == "https://github.com/o/r/actions/runs/9/job/2"


def test_none_after_three_minutes_without_checks_and_a_check_after_none_still_counts():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    assert ci.record(sid, SHA, [], now=T0 + timedelta(seconds=60)) is None  # still queued
    assert ci.record(sid, SHA, [], now=T0 + timedelta(minutes=3))["state"] == "none"
    assert ci.record(sid, SHA, [ci.from_check_run(run())], now=T0 + timedelta(minutes=4))["state"] == "passed"


def test_none_because_github_could_not_be_read_says_so():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    snap = ci.record(sid, SHA, [], now=T0 + timedelta(minutes=3), unreadable=True)
    assert snap["state"] == "none" and snap["reason"] == "unreadable"


# --- webhook deliveries ------------------------------------------------------------------------------

def test_a_delivery_is_claimed_once():
    assert ci.claim_delivery("d-1", "check_run") is True
    assert ci.claim_delivery("d-1", "check_run") is False
    ci.release_delivery("d-1")
    assert ci.claim_delivery("d-1", "check_run") is True


def test_old_deliveries_are_pruned():
    ci.claim_delivery("old", "status", now=utcnow() - timedelta(days=8))
    ci.claim_delivery("new", "status")
    assert ci.prune_deliveries() == 1
    assert ci.claim_delivery("old", "status") is True and ci.claim_delivery("new", "status") is False


# --- the sidebar ----------------------------------------------------------------------------------------

def test_failed_ci_on_an_unopened_chat_wants_attention_until_seen():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    mark_seen(sid, 10_000)
    row = get_session(sid)
    assert attention(row, None, ci.states([sid]).get(sid)) is None
    ci.record(sid, SHA, [ci.from_check_run(run(conclusion="failure"))], now=T0)
    row = get_session(sid)
    assert ci.states([sid])[sid][1] == "failed"
    assert attention(row, None, ci.states([sid]).get(sid)) == "failed"
    mark_seen(sid, 10_000)
    assert attention(get_session(sid), None, ci.states([sid]).get(sid)) is None


def test_passing_ci_wants_no_attention():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run())], now=T0)
    assert attention(get_session(sid), None, ci.states([sid]).get(sid)) is None


def test_a_working_chat_is_working_whatever_ci_says():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run(conclusion="failure"))], now=T0)
    set_status(sid, "running")
    assert attention(get_session(sid), None, ci.states([sid]).get(sid)) == "working"


def test_states_are_the_latest_snapshot_per_chat():
    a, b = session("a1"), session("b1")
    ci.pushed(a, SHA, now=T0)
    ci.record(a, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))], now=T0)
    append_event(b, "llm.message", {"message": {"role": "user", "content": "hi"}})
    states = ci.states([a, b])
    assert states[a][1] == "running" and b not in states


# --- CI that never finishes ----------------------------------------------------------------------------

def test_ci_unchanged_for_two_hours_while_running_is_unknown():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    ci.record(sid, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))], now=T0)
    seq = ci.states([sid])[sid][0]
    later = utcnow() + timedelta(hours=2)
    assert ci.states([sid], now=later - timedelta(seconds=1))[sid] == (seq, "running")
    assert ci.states([sid], now=later)[sid] == (seq, "unknown")


def test_a_queued_push_nobody_reports_on_goes_unknown_too_but_final_states_never_do():
    sid, done = session(), session("s2")
    ci.pushed(sid, SHA, now=T0)
    ci.pushed(done, "b" * 40, now=T0)
    ci.record(done, "b" * 40, [ci.from_check_run(run(head_sha="b" * 40))], now=T0)
    later = utcnow() + timedelta(days=3)
    assert ci.states([sid, done], now=later) == {sid: (ci.states([sid])[sid][0], "unknown"),
                                                 done: (ci.states([done])[done][0], "passed")}


def test_a_change_makes_it_known_again():
    sid = session()
    ci.pushed(sid, SHA, now=T0)
    assert ci.states([sid], now=utcnow() + timedelta(hours=3))[sid][1] == "unknown"
    ci.record(sid, SHA, [ci.from_check_run(run(status="in_progress", conclusion=None, completed=None))])
    assert ci.states([sid], now=utcnow() + timedelta(minutes=1))[sid][1] == "running"
