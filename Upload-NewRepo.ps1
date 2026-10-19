[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Test-Path -LiteralPath '.git') { throw '이미 Git 저장소입니다. git status와 remote를 먼저 확인하세요.' }
& git init -b main
if ($LASTEXITCODE -ne 0) { throw 'Git 초기화 실패' }
& git remote add origin https://github.com/yunjun1208/msa-team-integration.git
if ($LASTEXITCODE -ne 0) { throw '새 저장소 연결 실패' }
& git add .
if ($LASTEXITCODE -ne 0) { throw '파일 준비 실패' }
$paths = & git diff --cached --name-only
if ($LASTEXITCODE -ne 0) { throw '파일 목록 조회 실패' }
$blocked = @($paths | Where-Object { $_ -match '(^|/)(\.env($|\.)|credentials$|\.terraform/|\.teardown-private/)|\.(tfstate|tfvars|tfplan|pem|key)($|\.)' })
if ($blocked.Count -gt 0) { & git reset; throw '비밀값/state 파일이 발견되어 업로드를 중단했습니다.' }
& git diff --cached --stat
& git commit -m 'Prepare integrated MSA for AWS account and domain'
if ($LASTEXITCODE -ne 0) { throw '커밋 실패. git config user.name 및 user.email 설정을 확인하세요.' }
& git push -u origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub 인증 또는 빈 저장소 여부를 확인하세요. 기존 원격 기록을 강제로 덮어쓰지 않습니다.' }
