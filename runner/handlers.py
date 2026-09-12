import subprocess
import traceback


def handle_execution(payload: dict) -> dict:
    try:
        result = subprocess.run(
            payload["cmd"],
            shell=True,
            cwd="/workspace",
            capture_output=True,
            text=True,
            timeout=payload.get("timeout", 60)
        )
        return {"exit_code": result.returncode, "stdout": result.stdout[:10000], "stderr": result.stderr[:10000]}
    except Exception as e:
        traceback.print_exc()
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}
