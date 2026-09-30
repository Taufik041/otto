import argparse, asyncio, json, sys
from datetime import timezone

from aio_pika import connect
from sqlalchemy.exc import OperationalError

from shared import config
from shared.bus import actions_queue, results_queue
from shared.db import get_engine, init_db
from shared.events import load_events
from shared.sessions import delete_session, get_session
from brain.loop import resume_session, run_session

SUMMARY_WIDTH = 110


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="python -m brain.main",
        description="Run an Otto session from the command line.")
    p.add_argument("text", nargs="*", help="the task, or with --resume the follow-up message")
    p.add_argument("--session", default=config.SESSION_ID,
                   help=f"session id (default: SESSION_ID, now {config.SESSION_ID!r}; the runner must use the same)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true", help="continue the stored session with a new message")
    mode.add_argument("--show", action="store_true", help="print the stored session and its event timeline")
    mode.add_argument("--force-new", action="store_true", help="discard an existing session with this id first")
    args = p.parse_args(argv)
    if not args.show and not args.text:
        p.error("a task (or --resume message) is required")
    return args


def connect_db():
    """Persistence is not optional: stop here if the database can't be reached."""
    try:
        init_db()
    except OperationalError as e:
        url = get_engine().url.render_as_string(hide_password=True)
        sys.exit(f"[brain] cannot reach the database at {url}: {e.orig}\n"
                 "start it with `docker compose up -d postgres` or set DATABASE_URL")


def _fmt_ts(ts):
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text, width=SUMMARY_WIDTH):
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 3] + "..."


def summarize(ev) -> str:
    p = ev.payload
    if ev.type == "session.created":
        return f"model={p.get('model')} repo={p.get('repo')} task={p.get('task')!r}"
    if ev.type == "session.status":
        return p.get("status", "")
    if ev.type == "pr.opened":
        return f"#{p.get('number')} {p.get('html_url')}"
    if ev.type == "bus.action":
        return f"{p.get('kind')} {json.dumps(p.get('payload'))}"
    if ev.type == "bus.result":
        r = p.get("payload") or {}
        return f"{'ok' if p.get('ok') else 'FAILED'} exit={r.get('exit_code')} {r.get('stdout') or r.get('stderr') or ''}"
    if ev.type == "llm.message":
        m = p.get("message", {})
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = ", ".join(f"{tc['function']['name']}({tc['function']['arguments']})" for tc in m["tool_calls"])
            return f"assistant -> {calls}" + (f" | {m['content']}" if m.get("content") else "")
        if m.get("role") == "tool":
            return f"tool {m.get('tool_call_id')}: {m.get('content')}"
        return f"{m.get('role')}: {m.get('content')}"
    return json.dumps(p)


def show(sid):
    row = get_session(sid)
    if row is None:
        print(f"no session {sid!r}")
        return
    print(f"session {row.id}  status={row.status}  model={row.model}  repo={row.repo or '-'}")
    print(f"  title: {row.title}")
    print(f"  created {_fmt_ts(row.created_at)}  updated {_fmt_ts(row.updated_at)} (UTC)")
    print(f"  task: {_one_line(row.task)}")
    print(f"  branch: {row.work_branch or '-'}  pr: {row.pr_url or '-'}")
    print()
    for ev in load_events(sid):
        print(f"{ev.seq:>5}  {_fmt_ts(ev.ts)}  {ev.type:<15}  {_one_line(summarize(ev))}")


async def run(sid, text, resume):
    conn = await connect(config.BUS_URL)
    try:
        ch = await conn.channel()
        await ch.declare_queue(actions_queue(sid), durable=True)
        results = await ch.declare_queue(results_queue(sid), durable=True)
        if resume:
            await resume_session(ch, results, sid, text)
        else:
            await run_session(ch, results, sid, text)
    finally:
        await conn.close()


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sid = args.session
    connect_db()

    if args.show:
        show(sid)
        return

    if not args.resume and not config.is_available(config.DEFAULT_MODEL):
        sys.exit(f"[brain] no LLM model is available (default: {config.DEFAULT_MODEL!r}). Set OPENROUTER_API_KEY, "
                 "or OPENAI_API_KEY with OTTO_OPENAI_MODELS, or OTTO_API_KEY")

    existing = get_session(sid)
    if args.resume:
        if existing is None:
            sys.exit(f"[brain] no session {sid!r} to resume")
        if existing.status == "running":
            print(f"[brain] note: session {sid!r} is marked running (another brain, or one that crashed)", flush=True)
    elif existing is not None:
        if not args.force_new:
            sys.exit(f"[brain] session {sid!r} already exists (status={existing.status}). "
                     "Use --resume to continue it, or --force-new to discard it and start over.")
        delete_session(sid)
        print(f"[brain] discarded the old session {sid!r}", flush=True)

    asyncio.run(run(sid, " ".join(args.text), args.resume))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("[brain] interrupted")
