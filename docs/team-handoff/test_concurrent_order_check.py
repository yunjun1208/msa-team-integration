import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import concurrent_order_check as check

class RaceChecks(unittest.TestCase):
    def test_plan_does_not_login_or_order(self):
        with patch.object(check, "stock_snapshot", return_value=[{"id":3,"name":"QA test","stockQuantity":1}]), patch.object(check, "request") as request, patch("sys.argv", ["check"]), contextlib.redirect_stdout(io.StringIO()):
            check.main()
        request.assert_not_called()

    def test_non_qa_rejected(self):
        with patch.object(check, "stock_snapshot", return_value=[{"id":3,"name":"Real product","stockQuantity":1}]), patch("sys.argv", ["check", "--execute"]):
            with self.assertRaises(RuntimeError):
                check.main()

    def run_scenario(self, replay_id=11):
        lock = threading.Lock()
        ids = {}
        def request(path, method="GET", data=None, token=None, key=None):
            if "doLogin" in path:
                return 200, {"token":"PRIVATE_TOKEN", "email":"PRIVATE_EMAIL"}
            if path.endswith("mine"):
                return 200, [{"id": n} for n in [1, *ids.values()]]
            if path.endswith("create"):
                with lock:
                    if key not in ids:
                        ids[key] = 11 + len(ids)
                        order_id = ids[key]
                    else:
                        order_id = replay_id
                return (201 if order_id == 11 else 409), {"id": order_id,"status":"ORDERED" if order_id == 11 else "FAILED"}
            order_id = int(path.rsplit("/",1)[1])
            return 200, {"id":order_id,"status":"ORDERED" if order_id == 11 else "FAILED"}
        snapshots = [[{"id":3,"name":"QA test","stockQuantity":1},{"id":1,"stockQuantity":7}],
                     [{"id":3,"stockQuantity":0},{"id":1,"stockQuantity":7}],
                     [{"id":3,"stockQuantity":0},{"id":1,"stockQuantity":7}]]
        with tempfile.TemporaryDirectory() as folder:
            output = io.StringIO()
            report = Path(folder) / "result.json"
            with patch.object(check,"REPORT",report), patch.object(check,"stock_snapshot",side_effect=snapshots), patch.object(check,"request",side_effect=request), patch("builtins.input",return_value="tester"), patch.object(check.getpass,"getpass",return_value="PRIVATE_PASSWORD"), patch("sys.argv",["check","--execute"]), contextlib.redirect_stdout(output):
                if replay_id == 11:
                    check.main()
                else:
                    with self.assertRaises(SystemExit):
                        check.main()
            content = report.read_text(encoding="utf-8")
            for secret in ("PRIVATE_PASSWORD", "PRIVATE_TOKEN", "PRIVATE_EMAIL"):
                self.assertNotIn(secret, content + output.getvalue())
            return json.loads(content)

    def test_pass_requires_distinct_orders_and_same_key_replay(self):
        report = self.run_scenario()
        self.assertEqual(report["phase"], "passed")
        self.assertEqual(report["new_order_ids"], [11,12])

    def test_wrong_replay_is_failure(self):
        self.assertEqual(self.run_scenario(99)["phase"], "failed")

if __name__ == "__main__":
    unittest.main()
