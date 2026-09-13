import jwt, time, os
from dotenv import load_dotenv

load_dotenv(override=True)

def make_jwt():
    key = open(os.environ.get("GITHUB_APP_KEY_PATH", "")).read()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": os.environ["GITHUB_APP_ID"]}
    return jwt.encode(payload, key, algorithm="RS256")


import requests

def get_installation_token():
    inst = os.environ["GITHUB_INSTALLATION_ID"]
    r = requests.post(
        f"https://api.github.com/app/installations/{inst}/access_tokens",
        headers={"Authorization": f"Bearer {make_jwt()}",
                 "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()["token"]

REPO = "Taufik041/otto_test"   # or otto-gym, whichever the app is on

def open_pr(tok):
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{REPO}"

    # 1. base branch SHA (try main, fall back to master)
    base = "main"
    r = requests.get(f"{api}/git/ref/heads/{base}", headers=h)
    if r.status_code == 404:
        base = "master"
        r = requests.get(f"{api}/git/ref/heads/{base}", headers=h)
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]

    # 2. create branch otto/hello
    branch = "otto/hello"
    requests.post(f"{api}/git/refs", headers=h,
                  json={"ref": f"refs/heads/{branch}", "sha": base_sha})

    # 3. commit a file on that branch (Contents API: create-or-update)
    import base64
    content = base64.b64encode(b"Otto was here.\n").decode()
    requests.put(f"{api}/contents/OTTO.md", headers=h,
                 json={"message": "otto: add OTTO.md", "content": content, "branch": branch})

    # 4. open the PR
    r = requests.post(f"{api}/pulls", headers=h,
                      json={"title": "Otto's first PR", "head": branch, "base": base,
                            "body": "Opened by Otto via GitHub App auth."})
    r.raise_for_status()
    print("PR:", r.json()["html_url"])


if __name__ == "__main__":
    tok = get_installation_token()
    print("token:", tok[:12], "...")
    r = requests.get("https://api.github.com/installation/repositories",
                     headers={"Authorization": f"Bearer {tok}"})
    print("repos:", [x["full_name"] for x in r.json()["repositories"]])
    open_pr(tok)