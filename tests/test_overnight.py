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
    def test_targets_do_not_require_native_quoted_indexes(self):
        command = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'scripts/ops/Manage-Overnight.ps1'), [ref]$null, [ref]$null)
$function = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-ShutdownTargets'}, $true)
Invoke-Expression $function.Extent.Text
$targets = @(Get-ShutdownTargets @('module.eks.aws_eks_node_group.zonal["az-a"]', 'module.eks.aws_eks_node_group.zonal["az-c"]', 'aws_route53_record.management["argocd"]', 'module.ecr.aws_ecr_repository.main["member"]', 'aws_s3_bucket.deploy_verify'))
if ($targets.Count -ne 2 -or $targets -notcontains '-target=module.eks.aws_eks_node_group.zonal' -or $targets -notcontains '-target=aws_route53_record.management') { throw 'Invalid resource grouping or retention filter' }
if (($targets -join '') -match '[\[\]"]') { throw 'Native quoting still required' }
'PASS'
"""
        # Use Windows PowerShell 5.1 explicitly when available.
        shell = shutil.which("powershell") or PWSH
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                                cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(result.stdout.strip(), "PASS")

    def test_aws_wrapper_dispatches_to_cli_without_shadowing_it(self):
        command = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'scripts/ops/Manage-Overnight.ps1'), [ref]$null, [ref]$null)
$functions = $ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $true)
if ($functions.Name -contains 'aws') { throw 'Function shadows the native AWS CLI' }
$function = $functions | Where-Object Name -eq 'Invoke-AwsJson'
Invoke-Expression $function.Extent.Text
function Read-JsonCommand([string]$Program, [string[]]$Arguments) {
    [PSCustomObject]@{program=$Program; arguments=$Arguments}
}
$region = 'ap-northeast-2'
$result = Invoke-AwsJson @('sts', 'get-caller-identity')
if ($result.program -ne 'aws' -or $result.arguments[0] -ne 'sts' -or $result.arguments[1] -ne 'get-caller-identity') { throw 'Invalid CLI dispatch' }
'PASS'
"""
        result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
                                cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(result.stdout.strip(), "PASS")

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
