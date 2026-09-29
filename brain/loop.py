import json, asyncio
from openai import AsyncOpenAI
from openai import RateLimitError
from shared import config
from brain.tools import SYSTEM, TOOLS, KIND, missing_args
from brain.bus import bus_call, start_consumer, stop_consumer
from brain.resume import rebuild_messages
from shared.events import append_event, load_events
from shared.sessions import create_session, get_session, record_pr, set_status, transition

TOOL_CONTENT_LIMIT = 20000
TRUNCATED = "\n[... truncated]"


def tool_content(result, limit=TOOL_CONTENT_LIMIT) -> str:
    """json.dumps(result), trimming stdout/stderr (not the JSON text) so it stays valid JSON."""
    content = json.dumps(result)
    r = dict(result)
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

LLM_ATTEMPTS = 6


class LLMError(Exception):
    """The provider kept answering without a usable choice."""


def _no_choice(resp) -> str | None:
    """Why resp carries no usable choice, or None when it does."""
    if resp is None:
        return "empty response"
    # some providers answer 200 with {"error": ...}; the SDK keeps unknown body fields as attributes
    error = getattr(resp, "error", None)
    if error:
        return f"provider error: {error}"[:1000]
    if not getattr(resp, "choices", None):
        return "response has no choices"
    return None


async def _complete(client, **kwargs):
    """One chat completion, retried with backoff on rate limits and on responses with no choices."""
    for attempt in range(1, LLM_ATTEMPTS + 1):
        try:
            resp = await client.chat.completions.create(**kwargs)
        except RateLimitError:
            if attempt == LLM_ATTEMPTS:
                raise
            problem = "ratelimited"
        else:
            problem = _no_choice(resp)
            if problem is None:
                return resp
            if attempt == LLM_ATTEMPTS:
                raise LLMError(f"no usable LLM response after {LLM_ATTEMPTS} attempts; last: {problem}")
        wait = min(60, 10*attempt)
        print(f'[brain] {problem}, retrying in {wait}s', flush=True)
        await asyncio.sleep(wait)


def add_message(sid, messages, message):
    """Append to the conversation and store it; every message the model sees goes through here."""
    messages.append(message)
    append_event(sid, "llm.message", {"message": message})


async def run_session(ch, results, sid, task):
    """Create and run a new session (the CLI path). Returns the final messages list."""
    create_session(sid, task=task, repo_url=config.REPO_URL, model=config.MODEL)
    return await start_session(ch, results, sid, task)


async def start_session(ch, results, sid, task):
    """Run the first turn of a session whose row already exists. Returns the final messages list."""
    messages = []
    add_message(sid, messages, {"role": "system", "content": SYSTEM})
    add_message(sid, messages, {"role": "user", "content": task})
    return await run_loop(ch, results, sid, messages)


async def resume_session(ch, results, sid, text):
    """Continue a stored session with a new user message. Returns the final messages list."""
    events = load_events(sid)
    stored = [e.payload["message"] for e in events if e.type == "llm.message"]
    if not stored:
        raise LookupError(f"session {sid!r} has no conversation to resume")
    messages = rebuild_messages(events)
    if messages[:len(stored)] == stored:
        # store the synthetic results for calls cut off mid-turn, so the log matches what the model sees
        for m in messages[len(stored):]:
            append_event(sid, "llm.message", {"message": m})
    add_message(sid, messages, {"role": "user", "content": text})
    return await run_loop(ch, results, sid, messages)


async def run_loop(ch, results, sid, messages):
    """Drive the model from `messages` until it answers without tool calls (or the step cap)."""
    # built per call (not at import) so importing this module needs no API key
    client = AsyncOpenAI(
        base_url=config.BASE_URL,
        api_key=config.API_KEY
    )
    record = lambda type, payload: append_event(sid, type, payload)

    set_status(sid, "running")
    pending, consumer = start_consumer(results)
    # final statuses only replace "running": a session stopped meanwhile stays "stopped"
    try:
        await _steps(client, ch, pending, sid, messages, record)
    except (asyncio.CancelledError, KeyboardInterrupt):
        transition(sid, "interrupted", {"running"})
        raise
    except LLMError as e:
        record("error", {"stage": "llm", "message": str(e)})
        transition(sid, "failed", {"running"})
        raise
    except Exception:
        transition(sid, "failed", {"running"})
        raise
    finally:
        await stop_consumer(pending, consumer)
        await client.close()
    transition(sid, "done", {"running"})
    return messages


def _stopped(sid) -> bool:
    row = get_session(sid)
    return row is not None and row.status == "stopped"


async def _steps(client, ch, pending, sid, messages, record):
    for step in range(20):
        if _stopped(sid):
            print(f"[brain] session {sid} was stopped")
            return
        resp = await _complete(client, model=config.MODEL, messages=messages, tools=TOOLS)
        m = resp.choices[0].message

        if not m.tool_calls:
            print(f"\n[otto] {m.content}")
            # "" rather than None: the API rejects an assistant message with neither content nor tool calls
            add_message(sid, messages, {"role": "assistant", "content": m.content or ""})
            return

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
                        result = await bus_call(ch, pending, sid, kind, args, record=record)
                except Exception as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
                if kind == "git.open_pr" and result.get("exit_code") == 0 and result.get("html_url"):
                    record_pr(sid, result.get("number"), result["html_url"])
            print(f"[exit {result.get('exit_code')}] {(result.get('stdout') or result.get('stderr') or '')[:200]}")
            add_message(sid, messages, {"role": "tool", "tool_call_id": tc.id,
                                        "content": tool_content(result)})

    print("[stopped] iteration cap")
