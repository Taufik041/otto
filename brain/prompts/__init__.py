"""The system prompts. What Otto is lives in otto_about.md beside this file: every chat gets its
identity part (repo chats then get the agent's rules, brain.tools.AGENT); plain chats get all of
it, plus the live facts of the moment (chat_system), which the gateway sends with each job."""
import re
from pathlib import Path

from brain.tools import AGENT
from shared import config

MARKER = "<!-- plain chats only -->"
MAX_REPOS = 30  # repo names listed; the rest are counted


def _clean(text) -> str:
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.DOTALL).strip()


# {app_slug}: the GitHub App's name, as people mention it ("@<slug> review")
_ABOUT = (Path(__file__).parent / "otto_about.md").read_text().replace("{app_slug}", config.GITHUB_APP_SLUG or "<app>")
IDENTITY = _clean(_ABOUT.split(MARKER)[0])
ABOUT = _clean(_ABOUT)
SYSTEM = f"{IDENTITY}\n\n{AGENT}"  # repo chats

OFFLINE = ("Otto's workers are offline: repo tasks are paused, because the sandboxes run on Taufik's own "
           "hardware and it is off right now. Plain chat, like this one, still works. If the user asks, "
           "explain that plainly, and point to \"Ask Taufik to bring it up\" or \"Book a live demo\".")


def facts_text(facts: dict, model_label: str | None) -> str:
    """The live facts as lines; a fact that isn't known is left out rather than guessed."""
    lines = []
    if facts.get("workers") == "online":
        lines.append("Otto's workers are online: repo tasks can run.")
    elif facts.get("workers") == "offline":
        lines.append(OFFLINE)
    if model_label:
        lines.append(f"The model answering is {model_label}.")
    if isinstance(review := facts.get("review"), dict):
        lines.append(f"This chat is Otto's review of pull request #{review.get('number')} in {review.get('repo')}; "
                     "the review above is what Otto posted on GitHub. Answer questions about it. You can't change "
                     "the code or post to GitHub from this chat: for changes, the user starts a new chat and "
                     "mentions the repo with @.")
    repos = facts.get("repos")
    if repos is not None:
        names = ", ".join(repos[:MAX_REPOS]) + (f", and {len(repos) - MAX_REPOS} more" if len(repos) > MAX_REPOS else "")
        lines.append(f"The user's repos: {names}." if repos
                     else "The user has no repos connected yet (Settings → GitHub).")
    return "\n".join(f"- {line}" for line in lines)


def chat_system(facts: dict | None, model_label: str | None) -> str:
    """A plain chat's system prompt for this turn."""
    live = facts_text(facts or {}, model_label)
    return f"{ABOUT}\n\nRight now:\n{live}" if live else ABOUT
