import os
from dotenv import load_dotenv

load_dotenv(override=False)

# bus
BUS_URL = os.environ.get("BUS_URL", "amqp://guest:guest@localhost/")
SESSION_ID = os.environ.get("SESSION_ID", "s1")

# runner
WORKSPACE = os.environ.get("OTTO_WORKSPACE", "/workspace")

# brain
BASE_URL = os.environ.get("OTTO_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.environ.get("OTTO_API_KEY") or os.environ.get("API_KEY")
MODEL = os.environ.get("OTTO_MODEL", "openrouter/free")

# orchestrator
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "taufik041/otto-sandbox:dev")
K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")
SANDBOX_BUS_URL = os.environ.get("SANDBOX_BUS_URL", "amqp://guest:guest@rabbitmq:5672/")  # bus URL as seen from inside the pod

# github app
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID")
GITHUB_INSTALLATION_ID = os.environ.get("GITHUB_INSTALLATION_ID")
GITHUB_APP_KEY_PATH = os.environ.get("GITHUB_APP_KEY_PATH", "")
