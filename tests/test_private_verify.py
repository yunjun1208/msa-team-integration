"""Exercise private-verifier status handling without AWS access."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "private_verify", Path(__file__).resolve().parents[1] / "scripts/ops/run_private_verify.py"
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class PrivateVerifyTests(unittest.TestCase):
    def run_status(self, status):
        environment = {
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "VERIFY_SOURCE_BUCKET": "test-bucket", "VERIFY_CODEBUILD_PROJECT": "test-project",
        }
        with patch.dict(os.environ, environment), patch.object(verify.signal, "signal"), \
             patch.object(verify.subprocess, "run") as command, \
             patch.object(verify, "aws") as aws:
            aws.side_effect = [
                {"build": {"id": "test-project:123"}},
                {"builds": [{"buildStatus": status, "currentPhase": "COMPLETED"}]},
            ]
            if status == "SUCCEEDED":
                verify.main()
            else:
                with self.assertRaises(SystemExit):
                    verify.main()
            self.assertEqual(command.call_args_list[0].args[0][-1], "a" * 40)
            self.assertIn("--source-location-override", aws.call_args_list[0].args)
            self.assertEqual(aws.call_count, 2)

    def test_success_requires_remote_success(self):
        self.run_status("SUCCEEDED")

    def test_failed_remote_build_fails_workflow(self):
        self.run_status("FAILED")

    def test_query_failure_stops_remote_build(self):
        environment = {
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "VERIFY_SOURCE_BUCKET": "test-bucket", "VERIFY_CODEBUILD_PROJECT": "test-project",
        }
        with patch.dict(os.environ, environment), patch.object(verify.signal, "signal"), \
             patch.object(verify.subprocess, "run"), patch.object(verify, "aws") as aws:
            aws.side_effect = [{"build": {"id": "test-project:123"}}, RuntimeError("query failed"), {}]
            with self.assertRaises(RuntimeError):
                verify.main()
            self.assertEqual(aws.call_args.args, ("codebuild", "stop-build", "--id", "test-project:123"))


if __name__ == "__main__":
    unittest.main()
