import json, os
from dotenv import load_dotenv

load_dotenv(override=False)

# bus
BUS_URL = os.environ.get("BUS_URL", "amqp://guest:guest@localhost/")
SESSION_ID = os.environ.get("SESSION_ID", "s1")  # the runner's own session; only a default for the brain CLI

# database
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://otto:otto@localhost:5432/otto")

# runner
WORKSPACE = os.environ.get("OTTO_WORKSPACE", "/workspace")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # short-lived installation token, injected by the orchestrator

# brain
REPO_URL = os.environ.get("REPO_URL")  # recorded on the session; None when not known

# LLM providers. OTTO_BASE_URL/OTTO_API_KEY/OTTO_MODEL are the "custom" provider (the pre-providers setup)
BASE_URL = os.environ.get("OTTO_BASE_URL", "https://openrouter.ai/api/v1")
PROVIDER_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "custom": BASE_URL,
}


def numbered_keys(env, name) -> list[str]:
    """Values of NAME, NAME2, NAME3, ... (any numeric suffix) in numeric order; empty ones and repeats skipped."""
    found = []
    for var, value in env.items():
        suffix = var.removeprefix(name)
        if var.startswith(name) and (suffix == "" or suffix.isdigit()) and value.strip():
            found.append((int(suffix or 1), var, value.strip()))
    return list(dict.fromkeys(value for _, _, value in sorted(found)))


def provider_keys(env) -> dict[str, list[str]]:
    custom = (env.get("OTTO_API_KEY") or env.get("API_KEY") or "").strip()
    openai = (env.get("OPENAI_API_KEY") or "").strip()
    return {"openrouter": numbered_keys(env, "OPENROUTER_API_KEY"),
            "openai": [openai] if openai else [],
            "custom": [custom] if custom else []}


def _entry(m) -> dict:
    if not isinstance(m, dict) or not all(isinstance(m.get(k), str) and m[k] for k in ("id", "provider", "model")):
        raise ValueError(f"OTTO_MODELS: each entry needs string id, provider and model; got {m!r}")
    if m["provider"] not in PROVIDER_URLS:
        raise ValueError(f"OTTO_MODELS: unknown provider {m['provider']!r} in {m['id']!r}; "
                         f"expected one of {', '.join(PROVIDER_URLS)}")
    return {"id": m["id"], "provider": m["provider"], "model": m["model"], "label": m.get("label") or m["id"]}


def model_catalog(env) -> list[dict]:
    """The models users can pick from: OTTO_MODELS (a JSON list) if set, otherwise built from the env."""
    if env.get("OTTO_MODELS"):
        try:
            raw = json.loads(env["OTTO_MODELS"])
        except ValueError as e:
            raise ValueError(f"OTTO_MODELS is not valid JSON: {e}") from None
        if not isinstance(raw, list):
            raise ValueError("OTTO_MODELS must be a JSON list of {id, provider, model, label}")
        models = [_entry(m) for m in raw]
        ids = [m["id"] for m in models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"OTTO_MODELS has duplicate ids: {ids}")
        return models
    models = [{"id": "openrouter:openrouter/free", "provider": "openrouter", "model": "openrouter/free",
               "label": "OpenRouter Free"}]
    for name in (n.strip() for n in env.get("OTTO_OPENAI_MODELS", "").split(",")):
        if name:
            models.append({"id": f"openai:{name}", "provider": "openai", "model": name, "label": f"OpenAI {name}"})
    if env.get("OTTO_BASE_URL") or provider_keys(env)["custom"]:
        name = env.get("OTTO_MODEL") or "openrouter/free"
        models.append({"id": f"custom:{name}", "provider": "custom", "model": name, "label": f"Custom {name}"})
    return models


def default_model(models, keys, env) -> str | None:
    """OTTO_DEFAULT_MODEL, else the first model whose provider has a key."""
    return env.get("OTTO_DEFAULT_MODEL") or next((m["id"] for m in models if keys.get(m["provider"])), None)


PROVIDER_KEYS = provider_keys(os.environ)
MODELS = model_catalog(os.environ)
DEFAULT_MODEL = default_model(MODELS, PROVIDER_KEYS, os.environ)


def catalog_entry(model_id) -> dict | None:
    return next((m for m in MODELS if m["id"] == model_id), None)


def is_available(model_id) -> bool:
    """A catalog model whose provider has at least one key."""
    m = catalog_entry(model_id)
    return m is not None and bool(PROVIDER_KEYS.get(m["provider"]))


def resolve_model(model_id) -> dict:
    """The provider and model name for a session's model id, even one no longer in the catalog."""
    if m := catalog_entry(model_id):
        return m
    provider, sep, name = model_id.partition(":")
    if not (sep and provider in PROVIDER_URLS and name):
        # a bare model name, stored before providers existed: it ran on OTTO_BASE_URL (default OpenRouter)
        provider, name = ("custom" if PROVIDER_KEYS.get("custom") else "openrouter"), model_id
    return {"id": model_id, "provider": provider, "model": name, "label": model_id}

# orchestrator
SANDBOX_MAX_AGE_SECONDS = int(os.environ.get("SANDBOX_MAX_AGE_SECONDS", "3000"))  # < the 1h GitHub token
SANDBOX_IDLE_MINUTES = float(os.environ.get("SANDBOX_IDLE_MINUTES", "30"))  # runner exits after this long without actions
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "taufik041/otto-sandbox:dev")
K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")
SANDBOX_BUS_URL = os.environ.get("SANDBOX_BUS_URL", "amqp://guest:guest@rabbitmq:5672/")  # bus URL as seen from inside the pod

# gateway / worker
MAX_ACTIVE_SESSIONS = int(os.environ.get("MAX_ACTIVE_SESSIONS", "3"))    # agent sessions at work, per user
MAX_ACTIVE_SANDBOXES = int(os.environ.get("MAX_ACTIVE_SANDBOXES", "3"))  # agent sessions at work, everyone's
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "3"))
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]

# accounts
AUTH_SECRET = os.environ.get("AUTH_SECRET")  # signs login cookies and OAuth state; at least 32 characters
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
COOKIE_SECURE = FRONTEND_URL.startswith("https://")
DAILY_TOKEN_LIMIT = int(os.environ.get("DAILY_TOKEN_LIMIT", "50000"))  # a new user's limit


def model_prices(env) -> dict[str, dict[str, float]]:
    """MODEL_PRICES: JSON {model_id: {"input_per_1m": USD, "output_per_1m": USD}}. Unlisted models,
    and missing fields, cost 0."""
    if not env.get("MODEL_PRICES"):
        return {}
    try:
        raw = json.loads(env["MODEL_PRICES"])
    except ValueError as e:
        raise ValueError(f"MODEL_PRICES is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ValueError('MODEL_PRICES must be a JSON object: {"<model id>": {"input_per_1m": 0.15, '
                         '"output_per_1m": 0.6}}')
    prices = {}
    for model, p in raw.items():
        entry = {k: (p.get(k, 0) if isinstance(p, dict) else None) for k in ("input_per_1m", "output_per_1m")}
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in entry.values()):
            raise ValueError(f"MODEL_PRICES[{model!r}] needs non-negative numbers input_per_1m and "
                             f"output_per_1m; got {p!r}")
        prices[model] = {k: float(v) for k, v in entry.items()}
    return prices


MODEL_PRICES = model_prices(os.environ)

# github app
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID")
GITHUB_INSTALLATION_ID = os.environ.get("GITHUB_INSTALLATION_ID")
GITHUB_APP_KEY_PATH = os.environ.get("GITHUB_APP_KEY_PATH", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")          # the App's user OAuth: sign-in, installs
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG")            # github.com/apps/<slug>
