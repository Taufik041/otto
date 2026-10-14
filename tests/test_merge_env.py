"""deploy/aws/merge_env.py: a worksheet of settings merged into the server's compose .env, safely."""
import importlib.util
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("merge_env", ROOT / "deploy/aws/merge_env.py")
merge_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_env)

EXAMPLE = ROOT / "deploy/compose/.env.prod.example"
ENV = """# --- Required
POSTGRES_PASSWORD=old-pg
AUTH_SECRET=
# OTTO_SIGNUP_MODE=

# set by deploy/aws/bootstrap.sh: the Tailscale address, for the sandbox node
RABBITMQ_BIND=100.64.0.7
"""


def files(tmp_path, worksheet, env=ENV):
    w, e = tmp_path / "worksheet.env", tmp_path / ".env"
    w.write_text(worksheet)
    e.write_text(env)
    e.chmod(0o600)
    return w, e


def test_a_set_value_replaces_the_line_in_place_and_comments_stay(tmp_path):
    w, e = files(tmp_path, "AUTH_SECRET=s3cret\nPOSTGRES_PASSWORD=new-pg\n")
    assert merge_env.main([str(w), str(e)]) == 0
    assert e.read_text() == ENV.replace("old-pg", "new-pg").replace("AUTH_SECRET=\n", "AUTH_SECRET=s3cret\n")


def test_a_commented_out_setting_is_set_where_it_is_documented(tmp_path):
    w, e = files(tmp_path, "OTTO_SIGNUP_MODE=allowlist\n")
    merge_env.main([str(w), str(e)])
    assert "OTTO_SIGNUP_MODE=allowlist\n" in e.read_text() and "# OTTO_SIGNUP_MODE=" not in e.read_text()


def test_a_setting_not_in_env_yet_is_appended(tmp_path):
    w, e = files(tmp_path, "OPENAI_API_KEY=sk-test\n")
    merge_env.main([str(w), str(e)])
    assert e.read_text().endswith("OPENAI_API_KEY=sk-test\n")
    assert e.read_text().startswith(ENV)


def test_rabbitmq_bind_is_kept(tmp_path, capsys):
    w, e = files(tmp_path, "RABBITMQ_BIND=127.0.0.1\nAUTH_SECRET=x\n")
    merge_env.main([str(w), str(e)])
    assert "RABBITMQ_BIND=100.64.0.7\n" in e.read_text() and "RABBITMQ_BIND=127.0.0.1" not in e.read_text()
    assert "RABBITMQ_BIND" in capsys.readouterr().out


def test_an_empty_value_in_the_worksheet_changes_nothing(tmp_path):
    w, e = files(tmp_path, "POSTGRES_PASSWORD=\nAUTH_SECRET=x\n")
    merge_env.main([str(w), str(e)])
    assert "POSTGRES_PASSWORD=old-pg\n" in e.read_text()


def test_an_unknown_name_is_refused_and_nothing_is_written(tmp_path, capsys):
    w, e = files(tmp_path, "AUTH_SECRET=x\nAUTH_SECERT=typo\n")
    assert merge_env.main([str(w), str(e)]) == 1
    assert e.read_text() == ENV
    assert "AUTH_SECERT" in capsys.readouterr().err


def test_a_numbered_key_of_a_known_setting_is_known(tmp_path):
    w, e = files(tmp_path, "OPENROUTER_API_KEY2=or-2\n")
    assert merge_env.main([str(w), str(e)]) == 0
    assert e.read_text().endswith("OPENROUTER_API_KEY2=or-2\n")


@pytest.mark.parametrize("line", ["not a setting", "lower=case", "export AUTH_SECRET=x"])
def test_a_malformed_line_is_refused(tmp_path, line):
    w, e = files(tmp_path, f"AUTH_SECRET=x\n{line}\n")
    assert merge_env.main([str(w), str(e)]) == 1
    assert e.read_text() == ENV


def test_a_name_given_twice_is_refused(tmp_path):
    w, e = files(tmp_path, "AUTH_SECRET=x\nAUTH_SECRET=y\n")
    assert merge_env.main([str(w), str(e)]) == 1


def test_values_never_reach_the_output(tmp_path, capsys):
    w, e = files(tmp_path, "AUTH_SECRET=very-secret-value\nPOSTGRES_PASSWORD=another-secret\n")
    merge_env.main([str(w), str(e)])
    out = capsys.readouterr()
    assert "secret-value" not in out.out + out.err and "another-secret" not in out.out + out.err
    assert "AUTH_SECRET" in out.out and "POSTGRES_PASSWORD" in out.out


def test_the_file_keeps_its_mode_and_the_old_one_is_kept_as_a_backup(tmp_path):
    w, e = files(tmp_path, "AUTH_SECRET=x\n")
    merge_env.main([str(w), str(e)])
    assert stat.S_IMODE(e.stat().st_mode) == 0o600
    backups = list(tmp_path.glob(".env.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == ENV
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600


def test_dry_run_writes_nothing(tmp_path, capsys):
    w, e = files(tmp_path, "AUTH_SECRET=x\n")
    assert merge_env.main(["--dry-run", str(w), str(e)]) == 0
    assert e.read_text() == ENV and not list(tmp_path.glob(".env.bak-*"))
    assert "AUTH_SECRET" in capsys.readouterr().out


def test_comments_and_blank_lines_in_the_worksheet_are_fine(tmp_path):
    w, e = files(tmp_path, "# my notes\n\nAUTH_SECRET=x\r\n")
    assert merge_env.main([str(w), str(e)]) == 0
    assert "AUTH_SECRET=x\n" in e.read_text()


def test_every_name_in_the_example_is_known():
    names = merge_env.known_names(EXAMPLE.read_text())
    assert {"POSTGRES_PASSWORD", "OPENAI_API_KEY", "OTTO_ALLOWED_GITHUB", "RABBITMQ_BIND"} <= names


def test_nothing_changes_when_the_worksheet_says_what_env_says(tmp_path):
    w, e = files(tmp_path, "POSTGRES_PASSWORD=old-pg\n")
    assert merge_env.main([str(w), str(e)]) == 0
    assert not list(tmp_path.glob(".env.bak-*"))
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".env")] == [".env"]  # no temp file left
