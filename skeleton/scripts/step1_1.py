import subprocess, traceback

def run(cmd: str) -> dict:
    try:
        r = subprocess.run(
            ["docker", "exec", "-w", "/workspace", "otto-sb", "sh", "-c", cmd],
            capture_output=True,text=True, timeout=60
        )
        return {"exit_code": r.returncode, "stdout": r.stdout[:10000], "stderr": r.stderr[:10000]}
    except Exception as e:
        traceback.print_exc()
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}

if __name__== "__main__":
    while True:
        cmd = input("otto> ")
        res = run(cmd=cmd)

        if res["stdout"]:
            print(res["stdout"], end="")

        # Print errors
        if res["stderr"]:
            print(res["stderr"], end="", flush=True)

        # Show the exit code for failed commands
        if res["exit_code"] != 0:
            print(f"\nCommand exited with code {res['exit_code']}")