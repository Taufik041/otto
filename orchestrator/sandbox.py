import re, time

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from gateway import github_app
from shared import config
from shared.github import parse_repo

_batch = None
_core = None


def _batch_api():
    # loaded on first use (not at import) so importing this module needs no kubeconfig
    global _batch
    if _batch is None:
        k8s_config.load_kube_config()          # laptop→kind for now; load_incluster_config() when deployed
        _batch = client.BatchV1Api()
    return _batch


def _core_api():
    global _core
    if _core is None:
        k8s_config.load_kube_config()
        _core = client.CoreV1Api()
    return _core

def _job_name(session_id: str) -> str:
    # the Job name (and the pod's job-name label) must be a DNS-1123 label:
    # lowercase alphanumerics and '-', ending alphanumeric, at most 63 chars
    name = f"otto-{session_id}"
    if not re.fullmatch(r"[a-z0-9-]*[a-z0-9]", session_id) or len(name) > 63:
        raise ValueError(f"invalid session id {session_id!r}: use lowercase letters, digits and '-', "
                         f"ending in a letter or digit, at most {63 - len('otto-')} chars")
    return name

def github_app_configured() -> bool:
    return bool(config.GITHUB_APP_ID and config.GITHUB_APP_KEY_PATH)


def create_sandbox(session_id: str, repo_url: str, installation_id: int | None = None,
                   token: str | None = None) -> str:
    """Create the runner Job. Without a token, one is minted for installation_id (the installation
    the repo belongs to) when the GitHub App is configured: a fresh one, for this repo only.

    The token is short-lived (1h) and must never be logged.
    """
    name = _job_name(session_id)
    if token is None and installation_id and github_app_configured():
        token = github_app.mint_token(installation_id, [parse_repo(repo_url)[1]])
    env = [
        client.V1EnvVar(name="BUS_URL", value=config.SANDBOX_BUS_URL),
        client.V1EnvVar(name="SESSION_ID", value=session_id),
        client.V1EnvVar(name="REPO_URL", value=repo_url),
        client.V1EnvVar(name="SANDBOX_IDLE_MINUTES", value=str(config.SANDBOX_IDLE_MINUTES)),
    ]
    if token:
        env.append(client.V1EnvVar(name="GITHUB_TOKEN", value=token))

    container = client.V1Container(
        name="runner", image=config.SANDBOX_IMAGE, env=env,
        resources=client.V1ResourceRequirements(
            requests={"cpu": "200m", "memory": "300Mi"},
            limits={"cpu": "1", "memory": "1Gi"}))

    template = client.V1PodTemplateSpec(
        spec=client.V1PodSpec(restart_policy="Never", containers=[container]))

    # the deadline keeps a pod from outliving its 1h GitHub token; ttl cleans up finished Jobs
    spec = client.V1JobSpec(template=template, backoff_limit=0,
                            active_deadline_seconds=config.SANDBOX_MAX_AGE_SECONDS,
                            ttl_seconds_after_finished=100)

    job = client.V1Job(
        api_version="batch/v1", kind="Job",
        metadata=client.V1ObjectMeta(name=name),
        spec=spec)

    _batch_api().create_namespaced_job(body=job, namespace=config.K8S_NAMESPACE)
    return name

def destroy_sandbox(session_id: str):
    _batch_api().delete_namespaced_job(
        name=_job_name(session_id), namespace=config.K8S_NAMESPACE,
        body=client.V1DeleteOptions(propagation_policy="Foreground"))


def job_exists(session_id: str) -> bool:
    try:
        _batch_api().read_namespaced_job(name=_job_name(session_id), namespace=config.K8S_NAMESPACE)
        return True
    except ApiException as e:
        if e.status == 404:
            return False
        raise


def sandbox_pods(session_id: str) -> list[tuple[str, str]]:
    """(pod name, phase) for each pod of the session's Job."""
    pods = _core_api().list_namespaced_pod(namespace=config.K8S_NAMESPACE,
                                           label_selector=f"job-name={_job_name(session_id)}")
    return [(p.metadata.name, p.status.phase) for p in pods.items]


def pod_logs(pod_name: str) -> str:
    return _core_api().read_namespaced_pod_log(name=pod_name, namespace=config.K8S_NAMESPACE)


def sandbox_status(session_id: str) -> str:
    """"running" (Job alive, pod starting or up), "finished" (done, failed or going away) or "missing"."""
    try:
        job = _batch_api().read_namespaced_job(name=_job_name(session_id), namespace=config.K8S_NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            return "missing"
        raise
    st = job.status
    over = (job.metadata.deletion_timestamp or st.succeeded or st.failed
            or any(c.type in ("Complete", "Failed") and c.status == "True" for c in st.conditions or []))
    if over:
        return "finished"
    phases = [phase for _, phase in sandbox_pods(session_id)]
    if any(p in ("Succeeded", "Failed") for p in phases):
        return "finished"
    return "running"


def remove_sandbox(session_id: str, timeout=120, poll=1) -> bool:
    """Delete the session's Job if there is one and wait until it and its pods are gone.

    Returns whether there was a Job. Needed before re-creating a Job with the same name.
    """
    try:
        destroy_sandbox(session_id)
    except ApiException as e:
        if e.status != 404:
            raise
        return False
    deadline = time.monotonic() + timeout
    while job_exists(session_id) or sandbox_pods(session_id):
        if time.monotonic() > deadline:
            raise TimeoutError(f"job for session {session_id} still there after {timeout}s")
        time.sleep(poll)
    return True
