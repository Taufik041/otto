import json, os
from dotenv import load_dotenv

load_dotenv(override=False)


def flag(env, name, default=False) -> bool:
    """A boolean env var: 1/true/yes/on (any case) is True, 0/false/no/off False, unset the default."""
    value = (env.get(name) or "").strip().lower()
    if not value:
        return default
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be 1/true/yes/on or 0/false/no/off; got {env[name]!r}")


def csv(env, name, default="") -> list[str]:
    return [v.strip() for v in env.get(name, default).split(",") if v.strip()]


# "production" turns on the production settings (Secure cookies, no /docs unless OTTO_DOCS=1, ...)
ENV = os.environ.get("OTTO_ENV", "development").strip().lower()
PRODUCTION = ENV == "production"
VERSION = os.environ.get("OTTO_VERSION", "").strip()  # GET /health shows it; else the package version

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
    entry = {"id": m["id"], "provider": m["provider"], "model": m["model"], "label": m.get("label") or m["id"]}
    if isinstance(m.get("description"), str) and m["description"].strip():
        entry["description"] = m["description"].strip()  # one line for the frontend's picker
    return entry


def model_catalog(env) -> list[dict]:
    """The models users can pick from: OTTO_MODELS (a JSON list) if set, otherwise built from the env."""
    if env.get("OTTO_MODELS"):
        try:
            raw = json.loads(env["OTTO_MODELS"])
        except ValueError as e:
            raise ValueError(f"OTTO_MODELS is not valid JSON: {e}") from None
        if not isinstance(raw, list):
            raise ValueError("OTTO_MODELS must be a JSON list of {id, provider, model, label, description}")
        models = [_entry(m) for m in raw]
        ids = [m["id"] for m in models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"OTTO_MODELS has duplicate ids: {ids}")
        return models
    models = [{"id": "openrouter:openrouter/free", "provider": "openrouter", "model": "openrouter/free",
               "label": "Otto", "description": "Good for small tasks"}]
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
# a model call's total waiting on cooled-down keys; past it the call fails ("the model didn't respond")
MODEL_WAIT_BUDGET_SECONDS = float(os.environ.get("MODEL_WAIT_BUDGET_SECONDS", "120"))
LLM_TIMEOUT = float(os.environ.get("OTTO_LLM_TIMEOUT", "120"))  # seconds per request: long chats are slow
SANDBOX_MAX_AGE_SECONDS = int(os.environ.get("SANDBOX_MAX_AGE_SECONDS", "3000"))  # < the 1h GitHub token
SANDBOX_IDLE_MINUTES = float(os.environ.get("SANDBOX_IDLE_MINUTES", "30"))  # runner exits after this long without actions
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE") or "taufik041/otto-sandbox:dev"
# the sandbox cluster: a kubeconfig file and the namespace sandbox Jobs run in. Unset kubeconfig:
# workers are offline in production; in development the default kubeconfig (kind) is used
SANDBOX_KUBECONFIG = os.environ.get("OTTO_SANDBOX_KUBECONFIG", "").strip()
K8S_NAMESPACE = (os.environ.get("OTTO_SANDBOX_NAMESPACE") or os.environ.get("K8S_NAMESPACE") or "default").strip()
WORKERS_CHECK_SECONDS = float(os.environ.get("OTTO_WORKERS_CHECK_SECONDS", "30"))  # how long a reachability check counts
# the bus URL as a sandbox pod reaches it: from a k8s Secret (OTTO_RUNNER_AMQP_SECRET, key
# OTTO_RUNNER_AMQP_SECRET_KEY) when set, so it never sits in the Job spec; else this literal value
SANDBOX_BUS_URL = (os.environ.get("OTTO_RUNNER_AMQP_URL") or os.environ.get("SANDBOX_BUS_URL")
                   or "amqp://guest:guest@rabbitmq:5672/")
RUNNER_AMQP_SECRET = os.environ.get("OTTO_RUNNER_AMQP_SECRET", "").strip()
RUNNER_AMQP_SECRET_KEY = os.environ.get("OTTO_RUNNER_AMQP_SECRET_KEY", "url").strip()
# a sandbox's resources (Kubernetes quantities)
SANDBOX_RESOURCES = {
    "requests": {"cpu": os.environ.get("OTTO_SANDBOX_CPU_REQUEST", "200m"),
                 "memory": os.environ.get("OTTO_SANDBOX_MEMORY_REQUEST", "300Mi"),
                 "ephemeral-storage": os.environ.get("OTTO_SANDBOX_STORAGE_REQUEST", "1Gi")},
    "limits": {"cpu": os.environ.get("OTTO_SANDBOX_CPU_LIMIT", "1"),
               "memory": os.environ.get("OTTO_SANDBOX_MEMORY_LIMIT", "1Gi"),
               "ephemeral-storage": os.environ.get("OTTO_SANDBOX_STORAGE_LIMIT", "4Gi")},
}
SANDBOX_UID = int(os.environ.get("OTTO_SANDBOX_UID", "1000"))  # the image's non-root user (otto)

# gateway / worker
MAX_ACTIVE_SESSIONS = int(os.environ.get("MAX_ACTIVE_SESSIONS", "3"))    # agent sessions at work, per user
MAX_ACTIVE_SANDBOXES = int(os.environ.get("MAX_ACTIVE_SANDBOXES", "3"))  # agent sessions at work, everyone's
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "3"))
# accounts
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
# origins that may call the API with credentials and open the WebSocket; in production, the app's
CORS_ORIGINS = csv(os.environ, "CORS_ORIGINS", FRONTEND_URL if PRODUCTION else "http://localhost:5173,http://localhost:3000")
# origins that may also read GET /health (the landing page's status pill); no credentials
LANDING_ORIGINS = csv(os.environ, "OTTO_LANDING_ORIGINS", "" if PRODUCTION else "http://localhost:5174")  # dev: npm run dev:landing
DOCS = flag(os.environ, "OTTO_DOCS", default=not PRODUCTION)  # /docs, /redoc and /openapi.json
TRUST_PROXY = flag(os.environ, "OTTO_TRUST_PROXY")  # trust CF-Connecting-IP as the client's IP

AUTH_SECRET = os.environ.get("AUTH_SECRET")  # signs access tokens and OAuth state; at least 32 characters
ACCESS_TOKEN_MINUTES = int(os.environ.get("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.environ.get("REFRESH_TOKEN_DAYS", "30"))
# a token rotated this recently may come back once more (a lost response, two tabs): not theft
REFRESH_REUSE_GRACE_SECONDS = int(os.environ.get("REFRESH_REUSE_GRACE_SECONDS", "20"))
COOKIE_SECURE = PRODUCTION or FRONTEND_URL.startswith("https://")
# email through Resend: password resets, and "bring it back up" requests to OTTO_NOTIFY_TO.
# Without RESEND_API_KEY, development prints emails and production sends none (shared/email.py)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip() or None
EMAIL_FROM = os.environ.get("EMAIL_FROM", "").strip() or "Otto <noreply@taufi.dev>"
OTTO_NOTIFY_TO = os.environ.get("OTTO_NOTIFY_TO", "").strip() or None
DAILY_TOKEN_LIMIT = int(os.environ.get("DAILY_TOKEN_LIMIT", "300000"))  # a new user's limit

# who may make a new account. open: anyone; allowlist: GitHub logins in OTTO_ALLOWED_GITHUB,
# emails in OTTO_ALLOWED_EMAILS and approved access requests; closed: no one. Existing users
# always keep access
SIGNUP_MODES = ("open", "allowlist", "closed")
SIGNUP_MODE = os.environ.get("OTTO_SIGNUP_MODE", "allowlist" if PRODUCTION else "open").strip().lower()
if SIGNUP_MODE not in SIGNUP_MODES:
    raise ValueError(f"OTTO_SIGNUP_MODE must be one of {', '.join(SIGNUP_MODES)}; got {SIGNUP_MODE!r}")
ALLOWED_GITHUB = {v.lower().removeprefix("@") for v in csv(os.environ, "OTTO_ALLOWED_GITHUB")}
ALLOWED_EMAILS = {v.lower() for v in csv(os.environ, "OTTO_ALLOWED_EMAILS")}
ACCEPTING = flag(os.environ, "OTTO_ACCEPTING", default=True)  # false: "paused", no new accounts at all


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
# the gateway's /auth/github/callback as GitHub reaches it; sent as redirect_uri when set
GITHUB_CALLBACK_URL = os.environ.get("OTTO_GITHUB_CALLBACK_URL", "").strip()
