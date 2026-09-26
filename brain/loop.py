import json
from openai import OpenAI

from shared import config
from brain.tools import SYSTEM, TOOLS, KIND
from brain.bus import bus_call


async def run_session(ch, results, sid, task):
    # built per call (not at import) so importing this module needs no API key
    client = OpenAI(
        base_url=config.BASE_URL,
        api_key=config.API_KEY
    )

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]

    for step in range(20):
        resp = client.chat.completions.create(model=config.MODEL, messages=messages, tools=TOOLS)
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
                    result = await bus_call(ch, results, sid, kind, args)
                except Exception as e:
                    result = {"exit_code": 1, "stdout": "", "stderr": str(e)}
            print(f"[exit {result.get('exit_code')}] {(result.get('stdout') or result.get('stderr') or '')[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)[:20000]})


    print("[stopped] iteration cap")
