import copy
import json
from pathlib import Path
import tempfile
import unittest
import product_recovery_drill as drill


class Cluster:
    def __init__(self):
        self.context = drill.CONTEXT
        self.replicas = 1
        self.enabled = None
        self.app_uid = "app-original"
        self.dep_uid = "product-original"
        self.failure = None
        self.calls = []
        self.now = 0
        self.healthy = True
        self.appset = False

    def sleep(self, seconds):
        self.now += seconds

    def run(self, args):
        if args == ["kubectl", "config", "current-context"]:
            return self.context
        self.calls.append(args[4:])
        a = args[4:]
        if a[:2] == ["get", "application"]:
            return json.dumps({"metadata": {"uid": self.app_uid, "ownerReferences":
                [{"kind": "ApplicationSet"}] if self.appset else []},
                "spec": {"syncPolicy": {"automated": {"selfHeal": True, "enabled": self.enabled}}},
                "status": {"sync": {"status": "Synced", "revision": "baseline"},
                           "health": {"status": "Healthy" if self.healthy else "Degraded"}}})
        if a[:2] == ["get", "deployment"]:
            return json.dumps({"metadata": {"uid": self.dep_uid, "generation": 1},
                "spec": {"replicas": self.replicas}, "status": {"observedGeneration": 1,
                "availableReplicas": self.replicas, "replicas": self.replicas}})
        if a[0] == "patch":
            self.enabled = json.loads(a[-1])["spec"]["syncPolicy"]["automated"]["enabled"]
            if self.failure == "pause" and self.enabled is False:
                raise OSError("response lost after policy patch")
            if self.failure == "restore-policy" and self.enabled is None:
                raise OSError("policy restore denied")
            return "patched"
        if a[0] == "scale":
            self.replicas = int(a[-1].split("=")[1])
            if self.failure == "scale-down" and self.replicas == 0:
                raise OSError("response lost after scale")
            if self.failure == "scale-up" and self.replicas == 1:
                raise OSError("scale restore denied")
            return "scaled"
        if a[:2] == ["rollout", "status"]:
            if self.failure == "rollout":
                raise TimeoutError("not available")
            return "success"
        raise AssertionError(a)

    def mutations(self):
        return [a for a in self.calls if a[0] in ("patch", "scale")]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.cluster = Cluster()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        self.drill = drill.Drill(self.cluster.run, self.cluster.sleep, lambda: self.cluster.now)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_has_no_mutations_and_no_state_file(self):
        self.drill.run(path=self.path)
        self.assertEqual(self.cluster.mutations(), [])
        self.assertFalse(self.path.exists())

    def test_execute_restores_replicas_and_original_policy(self):
        self.drill.run(True, 15, self.path)
        self.assertEqual(self.cluster.replicas, 1)
        self.assertIsNone(self.cluster.enabled)
        self.assertEqual(json.loads(self.path.read_text())["phase"], "recovered")

    def test_ambiguous_mutation_errors_still_restore(self):
        for failure in ("pause", "scale-down"):
            with self.subTest(failure=failure):
                self.cluster.failure = failure
                with self.assertRaises(OSError):
                    self.drill.run(True, 15, self.path)
                self.assertEqual(self.cluster.replicas, 1)
                self.assertIsNone(self.cluster.enabled)

    def test_scale_restore_failure_still_attempts_policy_restore(self):
        self.cluster.failure = "scale-up"
        with self.assertRaisesRegex(RuntimeError, "Recovery needs attention"):
            self.drill.run(True, 15, self.path)
        self.assertIsNone(self.cluster.enabled)
        self.assertEqual(json.loads(self.path.read_text())["phase"], "recovery_required")

    def test_failed_rollout_is_not_reported_recovered(self):
        self.cluster.failure = "rollout"
        with self.assertRaises(RuntimeError):
            self.drill.run(True, 15, self.path)
        self.assertIsNone(self.cluster.enabled)
        self.assertEqual(json.loads(self.path.read_text())["phase"], "recovery_required")

    def test_context_and_unhealthy_or_appset_guards_precede_mutation(self):
        for key, value in (("context", "other-cluster"), ("healthy", False), ("appset", True)):
            with self.subTest(key=key):
                previous = getattr(self.cluster, key)
                setattr(self.cluster, key, value)
                with self.assertRaises(ValueError):
                    self.drill.run(True, 15, self.path)
                self.assertEqual(self.cluster.mutations(), [])
                setattr(self.cluster, key, previous)

    def test_recovery_refuses_recreated_deployment(self):
        state = self.drill.baseline()
        self.cluster.dep_uid = "different"
        with self.assertRaisesRegex(ValueError, "Resource recreated"):
            self.drill.recover(state, self.path)
        self.assertEqual(self.cluster.mutations(), [])

    def test_unfinished_previous_drill_blocks_new_fault(self):
        self.path.write_text(json.dumps({"phase": "active"}))
        with self.assertRaisesRegex(ValueError, "Previous drill"):
            self.drill.run(True, 15, self.path)
        self.assertEqual(self.cluster.mutations(), [])


if __name__ == "__main__":
    unittest.main()
