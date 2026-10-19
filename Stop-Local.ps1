[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& docker compose --env-file .env.local down
if ($LASTEXITCODE -ne 0) { throw '중지에 실패했습니다.' }
Write-Host '컨테이너를 중지했습니다. DB와 이미지는 볼륨에 보존됩니다.'
