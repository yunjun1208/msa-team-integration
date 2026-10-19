[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME/bin/javac.exe")) { throw 'JAVA_HOME을 JDK 17 경로로 설정하세요.' }
# ZIP의 긴 폴더 경로가 Windows 도구에 영향을 주지 않도록 짧은 경로에 푸는 것을 권장합니다.
$checks = @{
    member = @('*AdminAccessTest','*AdminDashboardAccessTest','*AdminDashboardServiceTest','*HealthGroupsTest','*InternalMemberAccessTest')
    product = @('*StockConcurrencyTest','*ReservationWorkflowTest','*LocalImageStorageTest')
    ordering = @('*OrderFeaturesTest')
    apigateway = @()
}
$bytes = New-Object byte[] 64
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$oldJwt = $env:JWT_SECRET
try {
    $env:JWT_SECRET = [Convert]::ToBase64String($bytes)
    foreach ($service in @('member','product','ordering','apigateway')) {
        $arguments = @('-p', "app/msa/$service", '--no-daemon', '--max-workers=2', 'test', 'bootJar')
        foreach ($pattern in $checks[$service]) { $arguments += @('--tests', $pattern) }
        & "./app/msa/$service/gradlew.bat" @arguments
        if ($LASTEXITCODE -ne 0) { throw "$service 빌드/테스트 실패" }
    }
} finally { $env:JWT_SECRET = $oldJwt }
