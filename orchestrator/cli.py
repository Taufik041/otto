import argparse, sys, time

from kubernetes.client.exceptions import ApiException

from orchestrator import sandbox
from shared import config

READY = "Listening for actions"
POLL = 2             # seconds between checks
GONE_TIMEOUT = 120   # for an old Job and its pods to go away
READY_TIMEOUT = 180  # for the new runner to start listening (image pull + clone + pip install)


class CliError(Exception):
    pass


def _wait(check, timeout, what):
    deadline = time.monotonic() + timeout
    while True:
        found = check()
        if found:
            return found
        if time.monotonic() > deadline:
            raise CliError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(POLL)


def _tail(text, lines=20):
    return "\n".join((text or "").splitlines()[-lines:])


def _logs(pod):
    try:
        return sandbox.pod_logs(pod)
    except ApiException:  # container not started yet
        return ""


def _gone(sid):
    return not sandbox.job_exists(sid) and not sandbox.sandbox_pods(sid)


def _listening(sid, last):
    for pod, phase in sandbox.sandbox_pods(sid):
        logs = _logs(pod)
        last["logs"] = logs
        if phase in ("Failed", "Succeeded"):
            raise CliError(f"pod {pod} {phase} before the runner was listening:\n{_tail(logs)}")
        if READY in logs:
            return pod
    return None


def destroy(sid):
    try:
        sandbox.destroy_sandbox(sid)
    except ApiException as e:
        if e.status != 404:
            raise
        print(f"[orchestrator] no job for session {sid}")
        return
    _wait(lambda: _gone(sid), GONE_TIMEOUT, f"the old job for session {sid} to go away")
    print(f"[orchestrator] destroyed the job for session {sid}")


def create(sid, repo, installation_id=None):
    destroy(sid)
    installation_id = installation_id or config.GITHUB_INSTALLATION_ID
    name = sandbox.create_sandbox(sid, repo, installation_id=installation_id)
    token = ("minted" if sandbox.github_app_configured() and installation_id
             else "none (set GITHUB_APP_ID, GITHUB_APP_KEY_PATH and --installation or GITHUB_INSTALLATION_ID)")
    print(f"[orchestrator] created job {name} for {repo} (GitHub token: {token})", flush=True)
    last = {"logs": ""}
    try:
        pod = _wait(lambda: _listening(sid, last), READY_TIMEOUT, f"'{READY}' in the runner logs")
    except CliError as e:
        if "timed out" not in str(e):
            raise
        raise CliError(f"{e}; last logs:\n{_tail(last['logs'])}") from None
    print(f"[orchestrator] runner {pod} is listening")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m orchestrator.cli", description="Manage Otto sandboxes.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="(re)create the session's sandbox Job and wait until its runner listens")
    c.add_argument("sid")
    c.add_argument("--repo", required=True, help="repo URL the sandbox clones")
    c.add_argument("--installation", help="GitHub App installation to mint the token for "
                                          "(default: GITHUB_INSTALLATION_ID)")
    d = sub.add_parser("destroy", help="delete the session's sandbox Job and wait until it is gone")
    d.add_argument("sid")
    args = p.parse_args(argv)

    try:
        if args.cmd == "create":
            create(args.sid, args.repo, args.installation)
        else:
            destroy(args.sid)
    except (CliError, ValueError, ApiException) as e:
        print(f"[orchestrator] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
