import json, asyncio
from shared import config, usage
from brain.providers import LLMError, ProviderUnusable, Stopped, complete
from brain.tools import CHAT_SYSTEM, SYSTEM, TOOLS, KIND, missing_args
from brain.bus import bus_call, start_consumer, stop_consumer
from brain.resume import rebuild_messages
from shared.events import append_event, load_events
from shared.github import parse_repo
from shared.models import TITLE_LENGTH, make_title
from shared.sessions import auto_title, create_session, get_session, record_pr, set_status, transition

TOOL_CONTENT_LIMIT = 20000
TRUNCATED = "\n[... truncated]"
# result fields the runner adds for the UI and the brain's finish (kept in bus.result); the model
# never sees them
UI_ONLY = ("diff", "diff_truncated", "added", "removed", "created", "diffstat", "base", "title",
           "dirty", "ahead", "work")


# actions that can leave work to finish: edits, writes, commands, and commits not yet pushed
CHANGES = ("fs.write", "fs.replace", "shell.exec", "git.commit")


class FinishFailed(Exception):
    """A step of the end-of-turn finish failed; its error event is recorded already."""


class LimitReached(Exception):
    """The session's user is at their daily token limit."""

    def __init__(self, info):
        super().__init__(f"daily token limit reached: {info}")
        self.info = info


def tool_content(result, limit=TOOL_CONTENT_LIMIT) -> str:
    """json.dumps(result) without the UI_ONLY fields, trimming stdout/stderr (not the JSON text) so
    it stays valid JSON."""
    r = {k: v for k, v in result.items() if k not in UI_ONLY}
    content = json.dumps(r)
    keys = [k for k in ("stdout", "stderr") if isinstance(r.get(k), str)]
    marker_len = len(json.dumps(TRUNCATED)) - 2  # escaped length, without the quotes
    while len(content) > limit and keys:
        k = max(keys, key=lambda k: len(r[k]))
        text = r[k].removesuffix(TRUNCATED)
        if not text:
            keys.remove(k)
            continue
        # each raw char is >= 1 JSON char, so this converges (at most one extra pass)
        keep = max(len(text) - (len(content) - limit) - marker_len, 0)
        r[k] = text[:keep] + TRUNCATED
        content = json.dumps(r)
    return content

def add_message(sid, messages, message):
    """Append to the conversation and store it; every message the model sees goes through here."""
    messages.append(message)
    append_event(sid, "llm.message", {"message": message})


async def run_session(ch, results, sid, task):
    """Create and run a new session (the CLI path). Returns the final messages list."""
    repo = "/".join(parse_repo(config.REPO_URL)) if config.REPO_URL else None
    create_session(sid, task=task, repo=repo, model=config.DEFAULT_MODEL)
    return await start_session(ch, results, sid, task)


async def start_session(ch, results, sid, task):
    """Run the first turn of a session whose row already exists. Returns the final messages list."""
    messages = []
    add_message(sid, messages, {"role": "system", "content": SYSTEM})
    add_message(sid, messages, {"role": "user", "content": task})
    return await run_loop(ch, results, sid, messages)


def _conversation(messages) -> list[dict]:
    return [m for m in messages if m.get("role") != "system"]


def replay(sid) -> list[dict]:
    """The stored conversation, as the model should see it next."""
    events = load_events(sid)
    stored = [e.payload["message"] for e in events if e.type == "llm.message"]
    if not stored:
        raise LookupError(f"session {sid!r} has no conversation to resume")
    messages = rebuild_messages(events)
    old, new = _conversation(stored), _conversation(messages)
    if new[:len(old)] == old:
        # store the synthetic results for calls cut off mid-turn, so the log matches what the model sees
        for m in new[len(old):]:
            append_event(sid, "llm.message", {"message": m})
    return messages


def use_system(sid, messages, content):
    """Make content the system prompt in force: first in messages, and stored (on replay the
    latest stored system message wins)."""
    message = {"role": "system", "content": content}
    if messages and messages[0] == message:
        return
    if messages and messages[0].get("role") == "system":
        messages[0] = message
    else:
        messages.insert(0, message)
    append_event(sid, "llm.message", {"message": message})


def _stored_already(messages, text) -> bool:
    """The gateway stores a follow-up when it's posted: then the replayed conversation ends with
    it, and the turn must not add it a second time. (The CLI's resumes aren't stored first.)"""
    last = messages[-1] if messages else {}
    return last.get("role") == "user" and last.get("content") == text


def has_conversation(sid) -> bool:
    """Whether the session has stored messages to resume (a session whose sandbox never started
    has none)."""
    return any(e.type == "llm.message" for e in load_events(sid))


async def resume_session(ch, results, sid, text):
    """Continue a stored session with a new user message, or (text None: a retry) from where its
    last turn stopped. Returns the final messages list.

    A plain chat that just got a repo continues here, under the agent's prompt."""
    messages = replay(sid)
    use_system(sid, messages, SYSTEM)
    if text is not None and not _stored_already(messages, text):
        add_message(sid, messages, {"role": "user", "content": text})
    return await run_loop(ch, results, sid, messages)


async def retry_chat(sid):
    """A plain chat's failed turn, again: the model answers the stored conversation as it is."""
    if not has_conversation(sid):
        return await chat_session(sid)
    messages = replay(sid)
    use_system(sid, messages, CHAT_SYSTEM)
    return await _turn(sid, messages, lambda record: _chat_step(sid, messages, record))


async def chat_session(sid, text=None):
    """One plain-chat turn: the model answers with no tools and no sandbox. text: a follow-up;
    None for the first turn, which answers the session's task."""
    if text is None:
        messages = []
        add_message(sid, messages, {"role": "system", "content": CHAT_SYSTEM})
        add_message(sid, messages, {"role": "user", "content": get_session(sid).task})
    else:
        messages = replay(sid)
        use_system(sid, messages, CHAT_SYSTEM)
        if not _stored_already(messages, text):
            add_message(sid, messages, {"role": "user", "content": text})
    return await _turn(sid, messages, lambda record: _chat_step(sid, messages, record))


async def run_loop(ch, results, sid, messages):
    """Drive the model from `messages` until it answers without tool calls (or the step cap)."""
    pending, consumer = start_consumer(results)
    try:
        return await _turn(sid, messages, lambda record: _agent_turn(ch, pending, sid, messages, record))
    finally:
        await stop_consumer(pending, consumer)


async def _agent_turn(ch, pending, sid, messages, record):
    """The model's steps, then the finish (unless the session was stopped or changed nothing)."""
    stopped, changed = await _steps(ch, pending, sid, messages, record)
    if not stopped and changed and not _stopped(sid):
        await finish(ch, pending, sid, messages, record)


def _last(messages, role) -> str:
    return next((m.get("content") or "" for m in reversed(messages)
                 if m.get("role") == role and (m.get("content") or "").strip()), "")


async def finish(ch, pending, sid, messages, record):
    """End an agent turn deterministically, whatever the model left undone: commit uncommitted
    changes (the message from this turn's request), push if the branch is ahead of the remote, and
    open the PR if there is none yet (title from the task, body: the model's final message). Each
    step is an ordinary bus action, so it shows as an event row. A failed step records an error
    and raises FinishFailed."""
    async def act(kind, args):
        result = await bus_call(ch, pending, sid, kind, args, record=record)
        if result.get("exit_code") != 0:
            why = (result.get("stderr") or result.get("stdout") or "failed").strip()
            record("error", {"stage": "finish", "step": kind, "message": f"{kind}: {why}"[:2000]})
            raise FinishFailed(kind)
        return result

    state = await act("git.status", {})
    if "dirty" not in state:
        return  # a sandbox from before the finish: it can't say, so leave it as the model did
    row = get_session(sid)
    dirty, ahead, work = state["dirty"], state.get("ahead"), state.get("work") or 0
    if dirty:
        await act("git.commit", {"message": make_title(_last(messages, "user") or row.task)})
        work += 1
    if dirty or ahead is None or ahead > 0:
        await act("git.push", {})
    if row.pr_url is None and work > 0:
        body = _last(messages, "assistant") or f"Changes by Otto for: {row.task}"
        pr = await act("git.open_pr", {"title": make_title(row.task), "body": body})
        if pr.get("html_url"):
            record_pr(sid, pr.get("number"), pr["html_url"])


async def _turn(sid, messages, steps):
    """Run steps(record) as the session's turn, with its status: running, then a final one."""
    record = lambda type, payload: append_event(sid, type, payload)

    set_status(sid, "running")
    # final statuses only replace "running": a session stopped meanwhile stays "stopped"
    try:
        await steps(record)
    except LimitReached as e:
        # a clean stop between calls: every tool call is answered, and the sandbox stays warm
        record("usage.limit_reached", e.info)
        transition(sid, "limited", {"running"})
        return messages
    except (asyncio.CancelledError, KeyboardInterrupt):
        transition(sid, "interrupted", {"running"})
        raise
    except Stopped:
        # POST /sessions/{id}/stop while the model call waited: the session is "stopped" already
        print(f"[brain] session {sid} was stopped while waiting on the model", flush=True)
        return messages
    except ProviderUnusable as e:
        # out of credit, a bad key, an unknown model: no retry or wait helps, and the chat says which
        record("error", {"stage": "model", "reason": e.reason, "provider": e.provider, "model": e.model,
                         "message": str(e)})
        transition(sid, "failed", {"running"})
        return messages
    except LLMError as e:
        record("error", {"stage": "llm", "message": str(e)})
        transition(sid, "failed", {"running"})
        raise
    except FinishFailed:
        transition(sid, "failed", {"running"})  # the error event says which step and why
        return messages
    except Exception:
        transition(sid, "failed", {"running"})
        raise
    if transition(sid, "done", {"running"}):
        await title_chat(sid, record, messages)
    return messages


TITLE_PROMPT = ("Write a title of 3 to 6 words for the chat below. Reply with the title only: plain "
                "text, no quotes, no trailing punctuation.")


def clean_title(text) -> str | None:
    """The model's title, tidied: its first line, without quotes, a "Title:" label or a trailing
    period, at most TITLE_LENGTH characters. None if nothing is left."""
    line = next((l for l in str(text or "").splitlines() if l.strip()), "").strip()
    line = line.removeprefix("Title:").removeprefix("title:").strip().strip("\"'`*").strip()
    line = line.rstrip(".!:;,").strip()
    if len(line) > TITLE_LENGTH:
        line = line[:TITLE_LENGTH].rsplit(" ", 1)[0]
    return line or None


def _pr_title(sid, pr_url) -> str | None:
    """The title the session's PR was opened with (from its git.open_pr result)."""
    for e in reversed(load_events(sid)):
        p = e.payload.get("payload") if e.type == "bus.result" else None
        if isinstance(p, dict) and p.get("html_url") == pr_url and p.get("title"):
            return p["title"]
    return None


async def title_chat(sid, record, messages):
    """After a chat's first completed turn, while its title is still its first message: the PR's
    title if it has one, else 3-6 words from its own model (one short call, counted in usage).
    Never fails the turn."""
    try:
        row = get_session(sid)
        if row is None or row.title_source != "auto":
            return  # renamed, or titled already
        if row.pr_url and (title := _pr_title(sid, row.pr_url)):
            auto_title(sid, make_title(title), "pr")
            return
        chat = [m for m in messages if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()]
        excerpt = "\n\n".join(f"{m['role']}: {m['content'][:1500]}" for m in chat[:2])
        resp = await _complete(sid, record, [{"role": "system", "content": TITLE_PROMPT},
                                             {"role": "user", "content": excerpt}])
        if title := clean_title(resp.choices[0].message.content):
            auto_title(sid, title, "model")
    except Exception as e:  # LimitReached, LLMError, anything: the chat keeps its first-message title
        print(f"[brain] no auto title for {sid}: {type(e).__name__}: {e}", flush=True)


async def _complete(sid, record, messages, **kw):
    """One LLM call on the session's model, within the user's daily token limit, and recorded."""
    row = get_session(sid)
    if row.user_id and (info := usage.limit_status(row.user_id)):
        raise LimitReached(info)
    # the model the session was created with, for every turn: never another provider or model
    model = config.resolve_model(row.model)
    resp = await complete(model["provider"], record, stopped=lambda: _stopped(sid), model=model["model"],
                          messages=messages, **kw)
    counts = getattr(resp, "usage", None)
    tokens = {k: int(getattr(counts, k, 0) or 0) for k in ("prompt_tokens", "completion_tokens")}
    usage.record(sid, row.user_id, model["provider"], row.model, **tokens)
    record("llm.usage", {"provider": model["provider"], "model": row.model, **tokens})
    return resp


async def _chat_step(sid, messages, record):
    resp = await _complete(sid, record, messages)
    add_message(sid, messages, {"role": "assistant", "content": resp.choices[0].message.content or ""})


def _stopped(sid) -> bool:
    row = get_session(sid)
    return row is not None and row.status == "stopped"


async def _steps(ch, pending, sid, messages, record) -> tuple[bool, bool]:
    """The model's steps until it answers without tool calls (or the step cap). Returns
    (stopped, changed): whether the session was stopped, and whether a step could have changed the
    workspace (see CHANGES)."""
    changed = False
    for step in range(20):
        if _stopped(sid):
            print(f"[brain] session {sid} was stopped")
            return True, changed
        resp = await _complete(sid, record, messages, tools=TOOLS)
        m = resp.choices[0].message

        if not m.tool_calls:
            print(f"\n[otto] {m.content}")
            # "" rather than None: the API rejects an assistant message with neither content nor tool calls
            add_message(sid, messages, {"role": "assistant", "content": m.content or ""})
            return False, changed

        if m.content:
            print(f"[thinking] {m.content}")

        tool_calls = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]
        add_message(sid, messages, {
            "role": "assistant",
            "content": m.content,
            "tool_calls": tool_calls
        })

        for tc in m.tool_calls:
            name = tc.function.name
            kind = KIND.get(name)
            result = {}
            if not kind:
                result = {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"unknown tool {name!r}; available: {', '.join(KIND)}"
                }
                print(f"[error] unknown tool {name!r}")
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if problem := missing_args(name, args):
                        result = {"exit_code": 1, "stdout": "", "stderr": problem}
                    else:
                        changed = changed or kind in CHANGES
                        result = await bus_call(ch, pending, sid, kind, args, record=record)
                except Exception as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
                if kind == "git.open_pr" and result.get("exit_code") == 0 and result.get("html_url"):
                    record_pr(sid, result.get("number"), result["html_url"])
            print(f"[exit {result.get('exit_code')}] {(result.get('stdout') or result.get('stderr') or '')[:200]}")
            add_message(sid, messages, {"role": "tool", "tool_call_id": tc.id,
                                        "content": tool_content(result)})

    print("[stopped] iteration cap")
    return False, changed
