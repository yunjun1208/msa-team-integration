"""Check destructive-plan guards using synthetic plans; never contact AWS."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(PWSH, "PowerShell is required")
class OvernightTests(unittest.TestCase):
    def run_guard(self, resource_type, actions):
        fixture = json.dumps({"resource_changes": [{
            "address": "test.resource", "type": resource_type, "change": {"actions": actions}
        }]})
        # Parse definitions only. The script's executable main body is never evaluated.
        command = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'scripts/ops/Manage-Overnight.ps1'), [ref]$null, [ref]$null)
$function = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-DurablePlan'}, $true)
Invoke-Expression $function.Extent.Text
try { Assert-DurablePlan (ConvertFrom-Json '__FIXTURE__'); 'ALLOWED' }
catch { 'BLOCKED' }
""".replace("__FIXTURE__", fixture)
        result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
                                cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
        return result.stdout.strip()

    def test_durable_storage_and_messages_cannot_be_deleted(self):
        for resource in ("aws_s3_bucket", "aws_s3_bucket_policy", "aws_ecr_repository",
                         "aws_dynamodb_table", "aws_sqs_queue", "aws_sns_topic", "aws_acm_certificate"):
            with self.subTest(resource=resource):
                self.assertEqual(self.run_guard(resource, ["delete"]), "BLOCKED")

    def test_replacing_a_bucket_is_also_blocked(self):
        self.assertEqual(self.run_guard("aws_s3_bucket", ["delete", "create"]), "BLOCKED")

    def test_ephemeral_infrastructure_can_be_deleted(self):
        self.assertEqual(self.run_guard("aws_eks_cluster", ["delete"]), "ALLOWED")

    def test_unchanged_durable_storage_is_allowed(self):
        self.assertEqual(self.run_guard("aws_s3_bucket", ["no-op"]), "ALLOWED")


if __name__ == "__main__":
    unittest.main()
