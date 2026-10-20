"""상품 서비스 장애/복구 실습. 기본은 읽기 전용 계획, --execute만 변경합니다.

사용자 AWS/kubeconfig가 있는 PowerShell에서 실행합니다. DB/Secret은 읽지 않습니다.
--execute는 실제 상품 API를 잠시 중단합니다. 승인된 점검 시간에만 실행하세요.
Argo CD auto-sync: https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

CONTEXT = "arn:aws:eks:ap-northeast-2:256187519952:cluster/msa-final-eks"
STATE = Path(__file__).with_name(".product-recovery-state.json")


def command(args):
    return subprocess.check_output(args, text=True, encoding="utf-8", timeout=210)


class Drill:
    def __init__(self, runner=command, sleep=time.sleep, clock=time.monotonic):
        self.runner, self.sleep, self.clock = runner, sleep, clock

    def k(self, *args):
        return self.runner(["kubectl", "--context", CONTEXT, "--request-timeout=15s", *args])

    def read(self, kind, name, namespace):
        return json.loads(self.k("get", kind, name, "-n", namespace, "-o", "json"))

    def guard_context(self):
        if self.runner(["kubectl", "config", "current-context"]).strip() != CONTEXT:
            raise ValueError("Expected msa-final-eks account/region context. No changes made.")

    def baseline(self):
        self.guard_context()
        app = self.read("application", "final-apps", "argocd")
        product = self.read("deployment", "product-depl", "soldesk")
        if any(o.get("kind") == "ApplicationSet" for o in app["metadata"].get("ownerReferences", [])):
            raise ValueError("ApplicationSet managed application: refuse temporary policy patch")
        status = app.get("status", {})
        if (status.get("sync", {}).get("status") != "Synced"
                or status.get("health", {}).get("status") != "Healthy"
                or app.get("operation")
                or status.get("operationState", {}).get("phase") == "Running"):
            raise ValueError("Argo must be Synced/Healthy with no operation")
        replicas = product["spec"].get("replicas", 1)
        if not 1 <= replicas <= 4 or product.get("status", {}).get("availableReplicas", 0) < replicas:
            raise ValueError("Product deployment is not ready")
        automated = app.get("spec", {}).get("syncPolicy", {}).get("automated")
        if not isinstance(automated, dict) or automated.get("enabled") is False:
            raise ValueError("Expected active standalone automated sync policy")
        return {"context": CONTEXT, "app_uid": app["metadata"]["uid"],
                "deployment_uid": product["metadata"]["uid"], "replicas": replicas,
                "enabled": automated.get("enabled"),
                "revision": status["sync"].get("revision"), "phase": "prepared"}

    def enabled(self, value):
        patch = {"spec": {"syncPolicy": {"automated": {"enabled": value}}}}
        self.k("patch", "application", "final-apps", "-n", "argocd",
               "--type=merge", "-p", json.dumps(patch))

    def scale(self, replicas):
        self.k("scale", "deployment/product-depl", "-n", "soldesk", "--replicas=" + str(replicas))

    @staticmethod
    def save(path, state):
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def recover(self, state, path):
        self.guard_context()
        if state.get("context") != CONTEXT or not 1 <= state.get("replicas", 0) <= 4:
            raise ValueError("Invalid recovery state")
        app = self.read("application", "final-apps", "argocd")
        product = self.read("deployment", "product-depl", "soldesk")
        if app["metadata"]["uid"] != state["app_uid"] or product["metadata"]["uid"] != state["deployment_uid"]:
            raise ValueError("Resource recreated; refuse to overwrite a different deployment")
        errors = []
        try:
            self.scale(state["replicas"])
        except Exception as error:
            errors.append(type(error).__name__)
        # Scale failure must not leave auto-sync disabled. Null removes a previously absent enabled key.
        try:
            self.enabled(state["enabled"])
        except Exception as error:
            errors.append(type(error).__name__)
        if not errors:
            try:
                self.k("rollout", "status", "deployment/product-depl", "-n", "soldesk",
                       "--timeout=180s", "--request-timeout=190s")
            except Exception as error:
                errors.append(type(error).__name__)
        state["phase"] = "recovery_required" if errors else "recovered"
        self.save(path, state)
        if errors:
            raise RuntimeError("Recovery needs attention: " + ", ".join(errors) + ". Run --recover with the same state file.")
        print("RECOVERED: original product replicas and Argo automated policy restored.", flush=True)

    def run(self, execute=False, duration=90, path=STATE):
        if not 15 <= duration <= 120:
            raise ValueError("Duration must be 15..120 seconds")
        if execute and path.exists() and json.loads(path.read_text(encoding="utf-8")).get("phase") != "recovered":
            raise ValueError("Previous drill not recovered. Run --recover first")
        state = self.baseline()
        print("PLAN: product-depl only; original replicas=" + str(state["replicas"])
              + "; outage window=" + str(duration) + "s; DB/Secret unchanged.", flush=True)
        if not execute:
            print("PLAN ONLY: no Kubernetes changes or recovery file written.", flush=True)
            return
        self.save(path, state)  # Persist restoration data before any potentially ambiguous network response.
        try:
            state["phase"] = "active"
            self.save(path, state)
            self.enabled(False)
            self.scale(0)
            deadline = self.clock() + 60
            while True:
                product = self.read("deployment", "product-depl", "soldesk")
                status = product.get("status", {})
                if (status.get("observedGeneration", 0) >= product["metadata"]["generation"]
                        and status.get("replicas", 0) == 0):
                    break
                if self.clock() >= deadline:
                    raise TimeoutError("Product pods did not stop")
                self.sleep(2)
            print("FAULT READY: 상품 API 중단. 지금 QA 장바구니에서 주문을 한 번 요청하세요.", flush=True)
            print("자동 복구까지 " + str(duration) + "초. 이 프로세스를 닫지 마세요.", flush=True)
            self.sleep(duration)
        finally:
            self.recover(state, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--recover", action="store_true")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--state", type=Path, default=STATE)
    args = parser.parse_args()
    drill = Drill()
    if args.recover:
        drill.recover(json.loads(args.state.read_text(encoding="utf-8")), args.state)
    else:
        drill.run(args.execute, args.duration, args.state)


if __name__ == "__main__":
    main()
