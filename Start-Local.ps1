[CmdletBinding()]
param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop을 설치하세요.' }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop을 실행하고 Linux containers 엔진이 준비될 때까지 기다리세요.' }
& docker compose version
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2가 필요합니다.' }
if (-not (Test-Path -LiteralPath '.env.local')) {
    function New-LocalSecret([int]$Size = 64) {
        $bytes = New-Object byte[] $Size
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [Convert]::ToBase64String($bytes)
    }
    $db = New-LocalSecret 32
    $storage = New-LocalSecret 32
    $values = @(
        "MYSQL_ROOT_PASSWORD=$(New-LocalSecret)", "MYSQL_PASSWORD=$db", "DB_PW=$db",
        "JWT_SECRET=$(New-LocalSecret)", "JWT_REFRESH_SECRET=$(New-LocalSecret)",
        "INTERNAL_SERVICE_TOKEN=$(New-LocalSecret)",
        "ADMIN_BOOTSTRAP_PASSWORD=$(New-LocalSecret 32)", 'ADMIN_BOOTSTRAP_EMAIL=admin@example.test',
        'MINIO_ROOT_USER=localstorage', "MINIO_ROOT_PASSWORD=$storage",
        'AWS_ACCESS_KEY_ID=localstorage', "AWS_SECRET_ACCESS_KEY=$storage"
    )
    [IO.File]::WriteAllLines((Join-Path $PSScriptRoot '.env.local'), $values, (New-Object Text.UTF8Encoding($false)))
}
& docker compose --env-file .env.local config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose 설정을 확인하세요.' }
$argsList = @('compose', '--env-file', '.env.local', 'up', '-d')
if (-not $SkipBuild) { $argsList += '--build' }
& docker @argsList
if ($LASTEXITCODE -ne 0) { throw '시작 실패. docker compose logs --tail=100 으로 확인하세요.' }
$ready = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    try {
        $result = Invoke-WebRequest 'http://localhost:8080/product-service/product/list' -UseBasicParsing -TimeoutSec 3
        if ($result.StatusCode -eq 200 -and $result.Headers['Content-Type'] -match 'json') { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}
if (-not $ready) { throw '상품 API 준비 시간 초과. docker compose logs --tail=100 으로 확인하세요.' }
Write-Host '접속: http://localhost:8080 / 관리자 ID: admin'
Write-Host '관리자 비밀번호는 .env.local의 ADMIN_BOOTSTRAP_PASSWORD 값을 확인하세요.'
Write-Host '전체 주문 검증: python local/smoke.py'
