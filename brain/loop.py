import json
from openai import AsyncOpenAI

from shared import config
from brain.tools import SYSTEM, TOOLS, KIND
from brain.bus import bus_call, start_consumer, stop_consumer

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


async def run_session(ch, results, sid, task):
    # built per call (not at import) so importing this module needs no API key
    client = AsyncOpenAI(
        base_url=config.BASE_URL,
        api_key=config.API_KEY
    )

    pending, consumer = start_consumer(results)
    try:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]

        for step in range(20):
            resp = await client.chat.completions.create(model=config.MODEL, messages=messages, tools=TOOLS)
            m = resp.choices[0].message

            if not m.tool_calls:
                print(f"\n[otto] {m.content}")
                return

            if m.content:
                print(f"[thinking] {m.content}")

            tool_calls = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in m.tool_calls]
            messages.append({
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
                        result = await bus_call(ch, pending, sid, kind, args)
                    except Exception as e:
                        result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
                print(f"[exit {result.get('exit_code')}] {(result.get('stdout') or result.get('stderr') or '')[:200]}")
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": tool_content(result)})


        print("[stopped] iteration cap")
    finally:
        await stop_consumer(pending, consumer)
        await client.close()
