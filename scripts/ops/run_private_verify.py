"""Submit tracked sources to the VPC verifier and relay its CloudWatch log."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time


def aws(*args):
    return json.loads(subprocess.check_output(
        ["aws", *args, "--region", "ap-northeast-2", "--output", "json"],
        text=True, timeout=60,
    ))


def main():
    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    revision = os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Invalid revision")
    bucket = os.environ["VERIFY_SOURCE_BUCKET"]
    project = os.environ["VERIFY_CODEBUILD_PROJECT"]
    key = f"sources/{revision}/{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}.zip"
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), revision], check=True)
        subprocess.run(["aws", "s3", "cp", str(archive), f"s3://{bucket}/{key}",
                        "--region", "ap-northeast-2", "--only-show-errors"], check=True, timeout=120)
    build = aws("codebuild", "start-build", "--project-name", project,
                "--source-location-override", f"{bucket}/{key}",
                "--environment-variables-override", f"name=REVISION,value={revision},type=PLAINTEXT")["build"]
    build_id = build["id"]
    print(f"Started private verifier: {build_id}", flush=True)
    finished = False
    token = None
    previous_phase = None
    deadline = time.monotonic() + 1200
    try:
        while time.monotonic() < deadline:
            build = aws("codebuild", "batch-get-builds", "--ids", build_id)["builds"][0]
            phase = build.get("currentPhase")
            if phase != previous_phase:
                print(f"Phase: {phase}", flush=True)
                previous_phase = phase
            logs = build.get("logs", {})
            if logs.get("groupName") and logs.get("streamName"):
                args = ["logs", "get-log-events", "--log-group-name", logs["groupName"],
                        "--log-stream-name", logs["streamName"], "--start-from-head"]
                if token:
                    args += ["--next-token", token]
                result = aws(*args)
                token = result.get("nextForwardToken")
                for event in result.get("events", []):
                    print(event["message"], end="" if event["message"].endswith("\n") else "\n", flush=True)
            status = build["buildStatus"]
            if status != "IN_PROGRESS":
                finished = True
                for item in build.get("phases", []):
                    for context in item.get("contexts", []):
                        print(context.get("message", ""), flush=True)
                print(f"Private verification: {status}", flush=True)
                if status != "SUCCEEDED":
                    raise SystemExit(1)
                return
            time.sleep(10)
        raise TimeoutError("Private verifier exceeded 20 minutes")
    finally:
        if not finished:
            aws("codebuild", "stop-build", "--id", build_id)


if __name__ == "__main__":
    main()
