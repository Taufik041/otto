#!/usr/bin/env python3
"""Merge a worksheet of settings (NAME=value lines, filled in on your laptop) into the server's
compose .env, safely:

    sudo -u deploy python3 /opt/otto/deploy/aws/merge_env.py ~deploy/incoming/otto.env \\
        /opt/otto/deploy/compose/.env

- A name already set in .env gets the new value on its own line; a commented-out `# NAME=` line
  (as .env.prod.example has them) is replaced where it is; any other name is appended.
- RABBITMQ_BIND is never changed: bootstrap.sh set it to the server's Tailscale address.
- An empty value in the worksheet changes nothing.
- A name .env.prod.example doesn't list (a typo), a malformed line or a name given twice refuses
  the whole worksheet, and nothing is written.
- .env is replaced atomically, keeping its mode and owner; the old one stays as .env.bak-<time>.
- Only names are printed, never values. --dry-run prints what would change and writes nothing.

Standard library only: it runs on the server's own python3.
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "compose/.env.prod.example"
KEEP = {"RABBITMQ_BIND"}  # bootstrap.sh's: the server's Tailscale address
SETTING = re.compile(r"([A-Z][A-Z0-9_]*)=(.*)")
DOCUMENTED = re.compile(r"#\s*([A-Z][A-Z0-9_]*)=.*")


def known_names(example: str) -> set[str]:
    """Every NAME the example lists, set (`NAME=`) or commented out (`# NAME=`)."""
    return {m.group(1) for line in example.splitlines() if (m := SETTING.fullmatch(line) or DOCUMENTED.fullmatch(line))}


def parse_worksheet(text: str, known: set[str]) -> tuple[dict[str, str], list[str]]:
    """(name -> value for every non-empty value, problems). Comments and blank lines are skipped."""
    values, seen, problems = {}, set(), []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = SETTING.fullmatch(line)
        if not m:
            problems.append(f"line {n}: not NAME=value")
            continue
        name, value = m.groups()
        if name in seen:
            problems.append(f"line {n}: {name} is given twice")
        elif name not in known and re.sub(r"\d+$", "", name) not in known:  # OPENROUTER_API_KEY2, ...
            problems.append(f"line {n}: {name} isn't a setting .env.prod.example lists (a typo?)")
        seen.add(name)
        if value:
            values[name] = value
    return values, problems


def merge(env: str, values: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """(the new .env, the names changed, the names kept as they are because they're in KEEP)."""
    lines = env.splitlines()
    kept = sorted(KEEP & values.keys())
    todo = {k: v for k, v in values.items() if k not in KEEP}
    changed = []
    set_at = {m.group(1): i for i, line in enumerate(lines) if (m := SETTING.fullmatch(line))}
    documented_at = {}
    for i, line in enumerate(lines):
        if (m := DOCUMENTED.fullmatch(line)) and m.group(1) not in documented_at:
            documented_at[m.group(1)] = i
    appended = []
    for name, value in todo.items():
        new = f"{name}={value}"
        if name in set_at:
            if lines[set_at[name]] != new:
                lines[set_at[name]] = new
                changed.append(name)
        elif name in documented_at:
            lines[documented_at[name]] = new
            changed.append(name)
        else:
            appended.append(new)
            changed.append(name)
    out = "\n".join(lines + appended)
    return (out + "\n" if out else out), changed, kept


def write_atomically(path: Path, text: str):
    """Replace path with text: a new file beside it (same mode and owner), renamed over it."""
    st = path.stat()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, st.st_mode & 0o7777)
        if os.geteuid() == 0:
            os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def backup(path: Path) -> Path:
    """A copy of path as .env.bak-<UTC time>, with the same mode."""
    dest = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, path.stat().st_mode & 0o777)
    with os.fdopen(fd, "w") as f:
        f.write(path.read_text())
    return dest


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 2:
        print("usage: merge_env.py [--dry-run] WORKSHEET ENV_FILE", file=sys.stderr)
        return 2
    worksheet, env_path = Path(args[0]), Path(args[1])
    values, problems = parse_worksheet(worksheet.read_text(), known_names(EXAMPLE.read_text()))
    if problems:
        print(f"{worksheet}: nothing merged:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    env = env_path.read_text()
    new, changed, kept = merge(env, values)
    for name in kept:
        print(f"kept {name} as it is in {env_path} (bootstrap.sh set it; change it there by hand)")
    if not changed:
        print(f"{env_path}: nothing to change")
        return 0
    print(("would set: " if dry else "set: ") + ", ".join(changed))
    if dry:
        return 0
    saved = backup(env_path)
    write_atomically(env_path, new)
    print(f"{env_path} updated; the old one is {saved.name}. Restart the stack to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
