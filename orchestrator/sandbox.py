from kubernetes import client, config as k8s_config

from shared import config

_batch = None


def _batch_api():
    # loaded on first use (not at import) so importing this module needs no kubeconfig
    global _batch
    if _batch is None:
        k8s_config.load_kube_config()          # laptop→kind for now; load_incluster_config() when deployed
        _batch = client.BatchV1Api()
    return _batch

def create_sandbox(session_id: str, repo_url: str, token: str | None = None) -> str:
    env = [
        client.V1EnvVar(name="BUS_URL", value=config.SANDBOX_BUS_URL),
        client.V1EnvVar(name="SESSION_ID", value=session_id),
        client.V1EnvVar(name="REPO_URL", value=repo_url),
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

    spec = client.V1JobSpec(template=template, backoff_limit=0,
                            ttl_seconds_after_finished=100)

    job = client.V1Job(
        api_version="batch/v1", kind="Job",
        metadata=client.V1ObjectMeta(name=f"otto-{session_id}"),
        spec=spec)

    _batch_api().create_namespaced_job(body=job, namespace=config.K8S_NAMESPACE)
    return f"otto-{session_id}"

def destroy_sandbox(session_id: str):
    _batch_api().delete_namespaced_job(
        name=f"otto-{session_id}", namespace=config.K8S_NAMESPACE,
        body=client.V1DeleteOptions(propagation_policy="Foreground"))
