# 로컬 실행 안내

이 패키지는 Docker Desktop의 **Linux containers**로 실행합니다. AWS 계정, Terraform apply, GitHub push 없이 로컬 DB와 앱을 띄웁니다.

## 시작

1. Docker Desktop을 설치·실행하고 엔진이 준비될 때까지 기다립니다. 첫 빌드에는 인터넷과 충분한 메모리(8GB 이상 할당 권장)가 필요합니다.
2. `C:\msa-team`처럼 짧은 경로에 압축을 풀고 프로젝트 폴더에서 PowerShell을 엽니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\Start-Local.ps1
```

3. http://localhost:8080 에 접속합니다. 관리자 ID는 `admin`, 비밀번호는 자동 생성된 `.env.local`의 `ADMIN_BOOTSTRAP_PASSWORD`입니다. 일반 회원은 회원가입 화면에서 만듭니다.
4. 관리자로 상품을 등록한 뒤 일반 회원으로 주문합니다. 이미지 파일은 로컬 MinIO에 저장합니다. 이미지 주소가 localhost를 사용하므로 같은 PC의 브라우저에서 접속하세요.
5. Python 3이 있다면 아래 명령으로 실제 HTTP 주문·중복 요청·재고·소유권을 검증합니다. 테스트 회원 2개, 상품과 주문이 DB에 추가됩니다.

```powershell
python local/smoke.py
```

자동 준비 확인은 상품 API까지이며, 전체 서비스의 동작 완료 여부는 smoke 검사로 확인합니다. 오류 시 아래 로그를 확인하세요.

```powershell
docker compose --env-file .env.local ps
docker compose --env-file .env.local logs --tail=100
```

## 중지·재시작

```powershell
powershell -ExecutionPolicy Bypass -File .\Stop-Local.ps1
powershell -ExecutionPolicy Bypass -File .\Start-Local.ps1 -SkipBuild
```

DB와 이미지는 Docker 볼륨에 남습니다. `.env.local`도 유지하세요. 기존 DB를 둔 채 이 파일을 재생성하면 DB 비밀번호 불일치가 생깁니다. 포트 8080/9000이 사용 중이면 해당 프로그램을 종료하세요. 로컬 초기화가 필요하면 데이터를 백업한 후 별도로 진행하세요.

## Java 회귀 테스트 (선택)

Docker 이미지 빌드는 실행 JAR를 만듭니다. 별도 회귀 검사는 JDK 17의 JAVA_HOME을 설정한 뒤 실행하세요.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
powershell -ExecutionPolicy Bypass -File .\Test-Java.ps1
```

기존 AWS/DB 연결이 필요한 contextLoads 대신 CI에서 사용하는 독립 테스트와 이번 회귀 테스트를 실행합니다. 결과를 확인한 후 실제 HTTP smoke 검사까지 진행하세요.

## AWS와의 차이

- 로컬: MySQL, MinIO, HTTP, Docker Compose. SNS/SES 발송은 비활성화되어 Outbox는 쌓이지만 실제 이메일은 오지 않습니다.
- AWS: 기존 Terraform/EKS/Argo CD 구성을 유지합니다. 쿠키 Secure 기본값은 true, S3 기본 인증 방식도 기존 IAM 역할입니다.
- 이 수정본은 AWS 배포 완료본이 아닙니다. `docs/11-test2-delivery.md`의 SES·Secret·배포 준비를 별도로 진행하세요.
- `terraform/backend.tf`, `terraform-k8s/backend.tf`, `Prepare-Secrets.ps1` 등에 기존 팀 계정·클러스터가 지정되어 있습니다. 다른 계정에 바로 apply하지 말고 계정·state·도메인·저장소 참조부터 맞추세요. 기존 state를 덮어쓰지 마세요.
- 로컬 MinIO의 products 버킷은 이미지 표시를 위해 익명 읽기이며 localhost에만 포트를 엽니다. 이 설정을 운영 S3 정책에 복사하지 마세요.

`.env.local`은 로컬 비밀값이며 공유·커밋하지 않습니다. 수정 ZIP에는 포함하지 않습니다.
