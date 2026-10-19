# Run on the same Windows PC and Windows account for DPAPI decryption.
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Stop', 'Resume')]
    [string]$Action = 'Prepare'
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 does not load the DPAPI assembly automatically.
Add-Type -AssemblyName System.Security
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$store = Join-Path $root '.overnight'
$bundlePath = Join-Path $store 'recovery.dpapi'
$statusPath = Join-Path $store 'status.json'
$phasePath = Join-Path $root 'terraform/overnight-phase.auto.tfvars.json'
$region = 'ap-northeast-2'
$account = '256187519952'
$cluster = 'msa-final-eks'
$context = "arn:aws:eks:${region}:${account}:cluster/$cluster"
Set-Location $root

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE). Stop here; fix and rerun." }
}
function Read-JsonCommand([string]$Program, [string[]]$Arguments) {
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program query failed; no resources will be treated as absent." }
    return (($result -join "`n") | ConvertFrom-Json)
}
function Invoke-AwsJson([string[]]$Arguments) {
    return Read-JsonCommand 'aws' ($Arguments + @('--region', $region, '--profile', 'default', '--output', 'json'))
}
function Write-Json([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))
}
function Save-Status($Value) { Write-Json $statusPath $Value }
function Read-Bundle {
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($bundlePath), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    try { return ([Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json) }
    finally { [Array]::Clear($bytes, 0, $bytes.Length) }
}
function Set-Inputs($Backup) {
    $env:TF_VAR_github_token = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Backup.repository.password))
    foreach ($pair in @(
        @('JWT_SECRET', 'TF_VAR_jwt_secret'),
        @('JWT_REFRESH_SECRET', 'TF_VAR_jwt_refresh_secret'),
        @('INTERNAL_SERVICE_TOKEN', 'TF_VAR_internal_service_token')
    )) {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Backup.app.($pair[0])))
        [Environment]::SetEnvironmentVariable($pair[1], $value, 'Process')
    }
}
function Resume-Settings([bool]$DnsEnabled, [string]$Snapshot) {
    $ipText = ([string](Invoke-RestMethod -Uri 'https://checkip.amazonaws.com' -TimeoutSec 15)).Trim()
    $ip = $null
    if (-not [Net.IPAddress]::TryParse($ipText, [ref]$ip) -or $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Cannot determine the current public IPv4 address.'
    }
    $cidrs = @(@($backup.publicCidrs) + @("$ipText/32") | Select-Object -Unique)
    Write-Json $phasePath @{
        enable_website_dns = $DnsEnabled; enable_management_dns = $DnsEnabled
        db_snapshot_identifier = $Snapshot; eks_public_access_cidrs = $cidrs
    }
}
function Assert-Account {
    $identity = Invoke-AwsJson @('sts', 'get-caller-identity')
    if ($identity.Account -ne $account) { throw 'Wrong AWS account.' }
}
function Connect-Cluster {
    Invoke-Checked 'aws' @('eks', 'update-kubeconfig', '--name', $cluster, '--region', $region, '--profile', 'default')
    $current = & kubectl config current-context
    if ($LASTEXITCODE -ne 0 -or $current -ne $context) { throw 'Wrong kubectl context.' }
    Invoke-Checked 'kubectl' @('--request-timeout=20s', 'get', 'nodes')
}
function Apply-Json($Value) {
    $Value | ConvertTo-Json -Depth 100 | & kubectl apply -f -
    if ($LASTEXITCODE -ne 0) { throw 'Kubernetes restore failed.' }
}
function Terraform-Apply([string]$Directory, [string[]]$Extra = @()) {
    Invoke-Checked 'terraform' (@("-chdir=$Directory", 'apply', '-input=false', '-auto-approve') + $Extra)
}
function Wait-Snapshot([string]$Name) {
    $deadline = (Get-Date).AddMinutes(60)
    do {
        $item = (Invoke-AwsJson @('rds', 'describe-db-snapshots', '--db-snapshot-identifier', $Name)).DBSnapshots[0]
        Write-Host "RDS snapshot: $($item.Status)"
        if ($item.Status -eq 'available') { return }
        if ($item.Status -notin @('creating', 'copying', 'available')) { throw 'Unexpected snapshot state.' }
        if ((Get-Date) -gt $deadline) { throw 'Snapshot wait exceeded one hour; do not destroy.' }
        Start-Sleep -Seconds 20
    } while ($true)
}
function Assert-DurablePlan($Plan) {
    foreach ($change in $Plan.resource_changes) {
        if ('delete' -notin $change.change.actions) { continue }
        if ($change.type -match '^aws_s3_bucket' -or $change.type -in @(
            'aws_ecr_repository', 'aws_dynamodb_table', 'aws_sqs_queue', 'aws_sns_topic', 'aws_cloudtrail',
            'aws_acm_certificate', 'aws_acm_certificate_validation'
        )) { throw "Protected durable resource in destroy plan: $($change.address)" }
    }
}
function Get-ShutdownTargets([string[]]$Addresses) {
    return @($Addresses | Where-Object {
        $_ -notmatch '^data\.' -and $_ -notmatch '\.data\.' -and
        $_ -notmatch '^module\.(ecr|s3|github_ci|cloudtrail|messaging)\.' -and
        $_ -notmatch '^module\.monitoring\.aws_sns_' -and
        $_ -notmatch '^aws_s3_bucket' -and $_ -notmatch '^aws_acm_certificate' -and
        $_ -notmatch '^aws_route53_record\.(website_certificate|management_certificate)' -and
        $_ -notmatch '^aws_dynamodb_table\.'
    } | ForEach-Object { "-target=$_" })
}
function New-ShutdownPlan([string]$Name) {
    $addresses = & terraform -chdir=terraform state list
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate infrastructure state.' }
    $targets = Get-ShutdownTargets $addresses
    if ($targets.Count -eq 0) { throw 'No shutdown targets found.' }
    $planFile = Join-Path $store $Name
    Invoke-Checked 'terraform' (@('-chdir=terraform', 'plan', '-destroy', '-input=false', '-var=enable_website_dns=false', '-var=enable_management_dns=false', "-out=$planFile") + $targets) | Out-Host
    $plan = Read-JsonCommand 'terraform' @('-chdir=terraform', 'show', '-json', $planFile)
    Assert-DurablePlan $plan
    $deletes = @($plan.resource_changes | Where-Object { 'delete' -in $_.change.actions })
    Write-Host "Durable-resource guard passed. Infrastructure deletions planned: $($deletes.Count)"
    return $planFile
}

Assert-Account
if ($Action -eq 'Prepare') {
    if (Test-Path $bundlePath) { throw 'Recovery bundle already exists. Keep it; do not overwrite an earlier recovery.' }
    Connect-Cluster
    $dirty = & git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Commit/push the overnight scripts before preparing the backup.' }
    $head = (& git rev-parse HEAD).Trim()
    $remote = (& git ls-remote origin refs/heads/main)
    if ($LASTEXITCODE -ne 0 -or ($remote -split '\s+')[0] -ne $head) { throw 'Local HEAD must match remote main.' }
    $db = (Invoke-AwsJson @('rds', 'describe-db-instances', '--db-instance-identifier', 'final-ordermsa-db')).DBInstances[0]
    if ($db.DBInstanceStatus -ne 'available') { throw 'RDS is not available.' }
    $app = Read-JsonCommand 'kubectl' @('get', 'secret', 'my-app-secrets', '-n', 'soldesk', '-o', 'json')
    $repo = Read-JsonCommand 'kubectl' @('get', 'secret', 'final-github-repository', '-n', 'argocd', '-o', 'json')
    $adminText = & kubectl get secret final-admin-config -n soldesk --ignore-not-found -o json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot query bootstrap admin secret.' }
    $admin = $null
    if ($adminText) { $admin = ($adminText -join "`n") | ConvertFrom-Json }
    if (-not $repo.data.password -or -not $app.data.JWT_SECRET) { throw 'Required credentials are missing.' }
    $allPv = Read-JsonCommand 'kubectl' @('get', 'pv', '-o', 'json')
    $claims = Read-JsonCommand 'kubectl' @('get', 'pvc', '-n', 'monitoring', '-o', 'json')
    $volumes = @()
    foreach ($claim in $claims.items) {
        $pv = $allPv.items | Where-Object { $_.metadata.name -eq $claim.spec.volumeName }
        if ($claim.status.phase -ne 'Bound' -or -not $pv.spec.csi.volumeHandle) { throw 'Monitoring volume is not a bound CSI volume.' }
        $volume = (Invoke-AwsJson @('ec2', 'describe-volumes', '--volume-ids', $pv.spec.csi.volumeHandle)).Volumes[0]
        $pvSpec = $pv.spec | ConvertTo-Json -Depth 50 | ConvertFrom-Json
        $pvSpec.persistentVolumeReclaimPolicy = 'Retain'
        $pvSpec.claimRef = [PSCustomObject]@{ namespace = 'monitoring'; name = $claim.metadata.name }
        $volumes += [PSCustomObject]@{
            id = $volume.VolumeId; zone = $volume.AvailabilityZone
            pv = @{ apiVersion = 'v1'; kind = 'PersistentVolume'; metadata = @{ name = $pv.metadata.name }; spec = $pvSpec }
            pvc = @{ apiVersion = 'v1'; kind = 'PersistentVolumeClaim'; metadata = @{ name = $claim.metadata.name; namespace = 'monitoring' }; spec = $claim.spec }
        }
    }
    if ($volumes.Count -lt 3) { throw 'Expected Grafana, Prometheus and Alertmanager volumes.' }
    New-Item -ItemType Directory -Path $store -Force | Out-Null
    $bundle = @{
        account = $account; revision = $head; repository = $repo.data; app = $app.data
        admin = $(if ($admin) { $admin.data } else { $null }); volumes = $volumes
        infraState = (& terraform -chdir=terraform state pull) -join "`n"
        k8sState = (& terraform -chdir=terraform-k8s state pull) -join "`n"
        publicCidrs = @((Invoke-AwsJson @('eks', 'describe-cluster', '--name', $cluster)).cluster.resourcesVpcConfig.publicAccessCidrs)
    }
    if ($LASTEXITCODE -ne 0 -or -not $bundle.infraState -or -not $bundle.k8sState) { throw 'State backup failed.' }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($bundle | ConvertTo-Json -Depth 100 -Compress))
    try {
        $encrypted = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        [IO.File]::WriteAllBytes($bundlePath, $encrypted)
    } finally { [Array]::Clear($bytes, 0, $bytes.Length) }
    # Verify DPAPI round-trip before any destructive step.
    $check = Read-Bundle
    if ($check.revision -ne $head -or $check.repository.password -ne $repo.data.password) { throw 'Backup verification failed.' }
    New-ShutdownPlan 'preview-shutdown.tfplan' | Out-Null
    Save-Status @{ phase = 'prepared'; snapshot = "final-overnight-$((Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss').ToLower())"; revision = $head; volumes = @($volumes | ForEach-Object { $_.id }) }
    Write-Host 'PREPARED. Credentials are encrypted for this Windows account. No AWS resources destroyed.'
    Write-Host "Monitoring EBS volumes preserved: $($volumes.Count)"
    Write-Host 'Next: run this script with -Action Stop to create a snapshot and shut down.'
    exit
}

if (-not (Test-Path $bundlePath) -or -not (Test-Path $statusPath)) { throw 'Run -Action Prepare first.' }
$backup = Read-Bundle
$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
if ($backup.account -ne $account) { throw 'Backup account mismatch.' }
Set-Inputs $backup

if ($Action -eq 'Stop') {
    if ($status.phase -eq 'stopped') { Write-Host 'Already stopped.'; exit }
    if ($status.phase -in @('prepared', 'snapshot-created')) {
    Connect-Cluster
    # Remove aliases while the ALB still exists; later plans must not query a deleted ALB.
    Write-Json $phasePath @{ enable_website_dns = $false; enable_management_dns = $false }
    Terraform-Apply 'terraform'
    # Explicitly suspend GitOps before stopping writers and taking the DB snapshot.
    $patchPath = Join-Path $store 'pause.json'
    Write-Json $patchPath @{ spec = @{ syncPolicy = @{ automated = @{ enabled = $false } } } }
    Invoke-Checked 'kubectl' @('patch', 'application', 'final-apps', '-n', 'argocd', '--type=merge', '--patch-file', $patchPath)
    foreach ($volume in $backup.volumes) {
        Write-Json $patchPath @{ spec = @{ persistentVolumeReclaimPolicy = 'Retain' } }
        Invoke-Checked 'kubectl' @('patch', 'pv', $volume.pv.metadata.name, '--type=merge', '--patch-file', $patchPath)
    }
    Invoke-Checked 'kubectl' @('delete', 'hpa', '--all', '-n', 'soldesk')
    Invoke-Checked 'kubectl' @('scale', 'deployment', '--all', '-n', 'soldesk', '--replicas=0')
    Invoke-Checked 'kubectl' @('wait', '--for=delete', 'pod', '--all', '-n', 'soldesk', '--timeout=600s')
    if ($status.phase -eq 'prepared') {
        Invoke-AwsJson @('rds', 'create-db-snapshot', '--db-instance-identifier', 'final-ordermsa-db', '--db-snapshot-identifier', $status.snapshot) | Out-Null
        $status.phase = 'snapshot-created'; Save-Status $status
    }
    Wait-Snapshot $status.snapshot
    $status.phase = 'snapshot-ready'; Save-Status $status
    }
    if ($status.phase -eq 'snapshot-ready') {
    # Remove app and management Ingress while both Argo CD and the ALB controller are alive.
    Invoke-Checked 'terraform' @('-chdir=terraform-k8s', 'destroy', '-input=false', '-auto-approve', '-target=helm_release.argocd_application', '-target=kubernetes_ingress_v1.management')
    $status.phase = 'ingresses-removed'; Save-Status $status
    }
    if ($status.phase -eq 'ingresses-removed') {
    $deadline = (Get-Date).AddMinutes(15)
    do {
        $loadBalancers = Invoke-AwsJson @('elbv2', 'describe-load-balancers')
        if (-not ($loadBalancers.LoadBalancers | Where-Object { $_.LoadBalancerName -eq 'final-shared-alb' })) { break }
        if ((Get-Date) -gt $deadline) { throw 'ALB not deleted yet; inspect Ingress finalizers.' }
        Write-Host 'Waiting for shared ALB deletion...'; Start-Sleep -Seconds 15
    } while ($true)
    Invoke-Checked 'terraform' @('-chdir=terraform-k8s', 'destroy', '-input=false', '-auto-approve')
    $status.phase = 'k8s-destroyed'; Save-Status $status
    }
    if ($status.phase -ne 'k8s-destroyed') { throw 'Unexpected shutdown checkpoint.' }
    $planFile = New-ShutdownPlan 'shutdown.tfplan'
    Wait-Snapshot $status.snapshot
    Write-Host 'Durable-resource guard passed. Applying the reviewed shutdown plan.'
    Invoke-Checked 'terraform' @('-chdir=terraform', 'apply', '-input=false', $planFile)
    $status.phase = 'stopped'; Save-Status $status
    Write-Host 'STOPPED. State, images, product S3, logs, queues, dedup, certificates, RDS snapshot and monitoring EBS are retained.'
    Write-Host 'Resume tomorrow on this Windows PC/account: powershell -ExecutionPolicy Bypass -File scripts/ops/Manage-Overnight.ps1 -Action Resume'
    exit
}

if ($Action -eq 'Resume') {
    if ($status.phase -notin @('stopped', 'resuming', 'resumed')) { throw 'Shutdown did not finish. Inspect state before resuming.' }
    $status.phase = 'resuming'; Save-Status $status
    Wait-Snapshot $status.snapshot
    # A local auto.tfvars file persists the restored snapshot choice for ordinary future applies.
    Resume-Settings $false $status.snapshot
    Invoke-Checked 'terraform' @('-chdir=terraform', 'init', '-input=false')
    Terraform-Apply 'terraform'
    Connect-Cluster
    Invoke-Checked 'kubectl' @('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=900s')
    Invoke-Checked 'terraform' @('-chdir=terraform-k8s', 'init', '-input=false')
    # Restore storage BEFORE Helm has a chance to create empty claims.
    Terraform-Apply 'terraform-k8s' @('-target=kubernetes_namespace_v1.monitoring', '-target=kubernetes_namespace_v1.soldesk', '-target=kubernetes_storage_class_v1.gp3', '-var=enable_app_sync=false')
    foreach ($volume in $backup.volumes) {
        $actual = (Invoke-AwsJson @('ec2', 'describe-volumes', '--volume-ids', $volume.id)).Volumes[0]
        if (-not $actual -or $actual.AvailabilityZone -ne $volume.zone) { throw 'Retained monitoring volume missing or wrong zone.' }
        $existingPv = Read-JsonCommand 'kubectl' @('get', 'pv', $volume.pv.metadata.name, '--ignore-not-found', '-o', 'json')
        if ($existingPv) {
            if ($existingPv.spec.csi.volumeHandle -ne $volume.id) { throw 'Existing PV refers to a different disk.' }
        } else { Apply-Json $volume.pv }
        $existingPvc = Read-JsonCommand 'kubectl' @('get', 'pvc', $volume.pvc.metadata.name, '-n', 'monitoring', '--ignore-not-found', '-o', 'json')
        if ($existingPvc) {
            if ($existingPvc.spec.volumeName -ne $volume.pv.metadata.name) { throw 'Existing claim refers to a different volume.' }
        } else { Apply-Json $volume.pvc }
    }
    if ($backup.admin) {
        Apply-Json @{ apiVersion = 'v1'; kind = 'Secret'; metadata = @{ name = 'final-admin-config'; namespace = 'soldesk' }; type = 'Opaque'; data = $backup.admin }
    }
    Terraform-Apply 'terraform-k8s' @('-var=enable_app_sync=false')
    Invoke-Checked 'kubectl' @('wait', 'externalsecret/database-credentials', '-n', 'soldesk', '--for=condition=Ready', '--timeout=300s')
    Terraform-Apply 'terraform-k8s' @('-var=enable_app_sync=true')
    $deadline = (Get-Date).AddMinutes(20)
    do {
        $app = Read-JsonCommand 'kubectl' @('--request-timeout=20s', 'get', 'application', 'final-apps', '-n', 'argocd', '-o', 'json')
        Write-Host "Application: $($app.status.sync.status) / $($app.status.health.status)"
        if ($app.status.sync.status -eq 'Synced' -and $app.status.health.status -eq 'Healthy') { break }
        if ((Get-Date) -gt $deadline) { throw 'Application did not become healthy. Resume can be rerun.' }
        Start-Sleep -Seconds 15
    } while ($true)
    Invoke-Checked 'aws' @('elbv2', 'wait', 'load-balancer-exists', '--names', 'final-shared-alb', '--region', $region, '--profile', 'default')
    Resume-Settings $true $status.snapshot
    Terraform-Apply 'terraform'
    Invoke-Checked 'python' @('-m', 'pip', 'install', 'PyYAML==6.0.3')
    $revision = (& git rev-parse HEAD).Trim()
    Invoke-Checked 'python' @('-u', 'scripts/ops/check_release.py', '--revision', $revision)
    $status.phase = 'resumed'; Save-Status $status
    Write-Host 'RESUMED AND VERIFIED. Confirm login and existing orders. Argo CD initial password may be newly generated.'
}
