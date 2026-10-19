[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$AlertEmail,
    [Parameter(Mandatory=$true)][string]$AdminCidr,
    [Parameter(Mandatory=$true)][string]$GithubOidcSubject,
    [string]$SesSenderEmail = ''
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$identityJson = & aws sts get-caller-identity --profile default --output json
if ($LASTEXITCODE -ne 0) { throw 'default 프로필 AWS 로그인을 확인하세요.' }
$identity = ($identityJson -join "`n") | ConvertFrom-Json
if ($identity.Account -ne '256187519952') { throw '계정이 256187519952가 아닙니다. 중단합니다.' }
if ($identity.Arn -notmatch '^arn:aws:iam::256187519952:(user|role)/') { throw 'EKS 관리 권한은 IAM 사용자/역할 ARN이어야 합니다. STS 세션 ARN을 사용할 수 없습니다.' }
if ($AdminCidr -notmatch '^([0-9]{1,3}\.){3}[0-9]{1,3}/32$') { throw '현재 PC 공인 IPv4/32를 입력하세요.' }
if ($AlertEmail -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { throw '알림 이메일을 확인하세요.' }
if ($SesSenderEmail -and $SesSenderEmail -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { throw 'SES 이메일을 확인하세요.' }
if ($GithubOidcSubject -notmatch '^repo:yunjun1208@336436724/msa-team-integration@1425166962:ref:refs/heads/main$') { throw '새 저장소 main의 Check AWS OIDC subject 결과를 입력하세요.' }
foreach ($file in @('terraform/terraform.tfvars','terraform-k8s/terraform.tfvars')) {
    if (Test-Path -LiteralPath $file) { throw "$file 파일이 이미 있습니다. 기존 설정을 보존하기 위해 중단합니다." }
}
$zoneJson = & aws route53 get-hosted-zone --id Z0919221R8VC8SHAV8CP --profile default --output json
if ($LASTEXITCODE -ne 0) { throw '기존 Hosted Zone 조회 실패' }
$zone = ($zoneJson -join "`n") | ConvertFrom-Json
if ($zone.HostedZone.Name -ne 'aws-cisco.com.' -or $zone.HostedZone.Config.PrivateZone) { throw '공개 aws-cisco.com 영역이 아닙니다.' }
$providersJson = & aws iam list-open-id-connect-providers --profile default --output json
if ($LASTEXITCODE -ne 0) { throw 'IAM OIDC 조회 실패' }
$providers = ($providersJson -join "`n") | ConvertFrom-Json
$existing = @($providers.OpenIDConnectProviderList | Where-Object { $_.Arn -eq 'arn:aws:iam::256187519952:oidc-provider/token.actions.githubusercontent.com' })
$oidc = if ($existing.Count -gt 0) { $existing[0].Arn } else { '' }
# JSON 문자열은 HCL 문자열 리터럴로 사용할 수 있습니다. 비밀번호는 이 파일에 저장하지 않습니다.
$infra = @(
    'eks_admin_principal_arn = ' + ($identity.Arn | ConvertTo-Json -Compress)
    'eks_public_access_cidrs = [' + ($AdminCidr | ConvertTo-Json -Compress) + ']'
    'alert_email = ' + ($AlertEmail | ConvertTo-Json -Compress)
    'github_oidc_subject = ' + ($GithubOidcSubject | ConvertTo-Json -Compress)
    'existing_github_oidc_provider_arn = ' + ($oidc | ConvertTo-Json -Compress)
    'manage_db_password = true'
    'customer_email_sender = ' + ($SesSenderEmail | ConvertTo-Json -Compress)
    'customer_email_enabled = false'
    'manage_ses_identities = false'
    'enable_website_dns = false'
    'enable_management_dns = false'
    'keep_legacy_node_group = false'
)
[IO.File]::WriteAllLines((Join-Path $PSScriptRoot 'terraform/terraform.tfvars'), [string[]]$infra, (New-Object Text.UTF8Encoding($false)))
$k8s = @('enable_app_sync = false','enable_management_ingress = false','github_revision = "main"')
[IO.File]::WriteAllLines((Join-Path $PSScriptRoot 'terraform-k8s/terraform.tfvars'), $k8s, (New-Object Text.UTF8Encoding($false)))
Write-Host '계정/도메인 확인 및 개인 tfvars 준비 완료. AWS 자원은 생성하지 않았습니다.'
Write-Host '다음은 AWS-FIRST-RUN.md의 state bootstrap 단계입니다.'
