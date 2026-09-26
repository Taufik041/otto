import jwt, time
import requests

from shared import config


def make_jwt():
    key = open(config.GITHUB_APP_KEY_PATH).read()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": config.GITHUB_APP_ID}
    return jwt.encode(payload, key, algorithm="RS256")


def get_installation_token():
    inst = config.GITHUB_INSTALLATION_ID
    r = requests.post(
        f"https://api.github.com/app/installations/{inst}/access_tokens",
        headers={"Authorization": f"Bearer {make_jwt()}",
                 "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()["token"]
