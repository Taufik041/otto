"""deploy/aws/bootstrap.sh never waits for input: every apt call goes through apt_get, which runs
apt-get with -y, keeps changed config files, and gives it no stdin; DEBIAN_FRONTEND and
NEEDRESTART_MODE are exported before the first one (so installers it runs get them too); and no
installer is piped into a shell (where apt would read the rest of the script as its stdin)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = ROOT / "deploy/aws/bootstrap.sh"
APT = re.compile(r"(?<![\w/.-])(apt-get|apt|aptitude|dpkg)(?![\w/.-])")


def code_lines() -> list[tuple[int, str]]:
    """(line number, line) for every line that isn't a comment or inside a heredoc."""
    out, heredoc = [], None
    for n, line in enumerate(BOOTSTRAP.read_text().splitlines(), 1):
        if heredoc:
            heredoc = None if line.strip() == heredoc else heredoc
            continue
        if m := re.search(r"<<-?'?(\w+)'?", line):
            heredoc = m.group(1)
        if not line.lstrip().startswith("#"):
            out.append((n, line))
    return out


def prelude() -> str:
    """The script from its first line to apt_get's definition: the settings every apt call gets."""
    text = BOOTSTRAP.read_text()
    end = text.index("apt_get() {")
    return text[:text.index("\n", end) + 1]


def test_every_apt_call_goes_through_apt_get():
    raw = [(n, line) for n, line in code_lines()
           if APT.search(line) and "apt_get()" not in line and "dpkg --print-architecture" not in line]
    assert raw == []
    calls = [n for n, line in code_lines() if re.search(r"\bapt_get\b", line) and "apt_get()" not in line]
    assert len(calls) >= 4  # update and install, for the base packages and for Docker


def test_the_settings_come_before_the_first_apt_call():
    first_call = min(n for n, line in code_lines() if re.search(r"\bapt_get (update|install)", line))
    defined = len(prelude().splitlines())
    assert defined < first_call


def test_no_installer_is_piped_into_a_shell():
    assert [line for _, line in code_lines() if re.search(r"\|\s*(sudo\s+)?(ba)?sh\b", line)] == []


def test_apt_get_runs_without_a_prompt_or_stdin(tmp_path):
    """Run the prelude's apt_get against a stand-in apt-get, with stdin a pipe full of answers."""
    fake = tmp_path / "apt-get"
    fake.write_text('#!/bin/bash\n'
                    'echo "args: $*"\n'
                    'echo "frontend: $DEBIAN_FRONTEND"\n'
                    'echo "needrestart: $NEEDRESTART_MODE"\n'
                    'echo "stdin: $(readlink /proc/self/fd/0)"\n'
                    'cat "$APT_CONFIG"\n')
    fake.chmod(0o755)
    script = f"{prelude()}\napt_get install something\n"
    r = subprocess.run(["bash", "-c", script], input="y\ny\ny\n", capture_output=True, text=True,
                       env={"PATH": f"{tmp_path}:/usr/bin:/bin"}, timeout=10)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "args: -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install something" in out
    assert "frontend: noninteractive" in out
    assert "needrestart: a" in out
    assert "stdin: /dev/null" in out
    assert '"--force-confdef"; "--force-confold"' in out and 'Assume-Yes "true"' in out


def test_it_warns_on_anything_but_ubuntu_24_04():
    text = BOOTSTRAP.read_text()
    assert '[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] || echo "warning: written for Ubuntu 24.04' in text
