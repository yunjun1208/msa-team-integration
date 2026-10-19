# 수정 및 검증 보고서 (2026-10-19)

## 수정

1. AWS 없는 로컬 실행용 compose.yaml, Java Dockerfile, MinIO 초기화와 볼륨을 추가했습니다. 기존 AWS 배포 설정은 유지했습니다.
2. 로컬 Nginx에 서비스 API 프록시를 추가했습니다. 기존 운영 Nginx는 ALB의 API 분기와 함께 사용하는 구성이므로 수정하지 않았습니다.
3. 관리자 쿠키의 Secure 속성을 설정으로 분리했습니다. 기본은 true, 로컬 Compose에서만 false입니다. 기본 동작 및 로컬 동작 회귀 테스트를 포함했습니다.
4. S3 클라이언트에 선택적 endpoint/path-style 설정, 이미지 URL에 선택적 public-base-url을 추가했습니다. 로컬 MinIO 내부 주소가 브라우저 URL로 노출되지 않도록 했습니다. 공백 등 경로 문자를 인코딩하고 업로드 입력 스트림을 닫습니다.
5. Start/Stop-Local.ps1, Test-Java.ps1, local/smoke.py와 LOCAL-RUN.md를 추가했습니다. 비밀값은 최초 실행 때 생성하고 재사용합니다.

## 이번 환경에서 확인한 결과

- 기존 Python 테스트 18개 통과.
- 프런트엔드 Node 테스트 7개 통과.
- Docker Compose config 검사 통과 (실제 .env.local을 읽지 않는 --no-env-resolution 검사).
- Start/Stop PowerShell 구문 및 Python smoke 스크립트 컴파일 검사 통과.
- Terraform fmt -check -recursive 통과. 이는 validate/plan/apply 검증이 아닙니다.

## 검증하지 못한 항목

- JDK 17/Gradle 의존성 다운로드 후 member/product Java 빌드가 캐시 JAR AccessDeniedException으로 중단됐습니다. 코드 컴파일·Java 테스트 성공으로 보고하지 않습니다. 추가한 회귀 테스트도 실제 통과 확인 전입니다.
- kubectl kustomize는 경로 Access is denied로 중단됐습니다.
- Docker 엔진 파이프가 없어 Compose 컨테이너 실행과 실제 MySQL·HTTP 주문 검사는 수행하지 못했습니다. local/smoke.py는 사용자가 실행해야 합니다.
- AWS 자원을 생성·변경하지 않았습니다. SES 메일, EKS 배포, Secrets Manager 회전 등은 별도 실환경 검증이 필요합니다.

## AWS 실행 전 확인

원본은 기존 팀 계정의 state bucket/account ID, EKS context, 저장소와 도메인 참조를 포함합니다. 계정이 다르면 backend와 변수, Prepare-Secrets 및 Argo/GitHub 설정을 검토해야 합니다. 이번 로컬 구성은 기존 AWS를 자동 연결하거나 이전하지 않습니다.

원본 ZIP과 GitHub 저장소는 변경하지 않았습니다. 이 파일은 실행 준비 수정본이며 전체 운영 검증 완료 보고서가 아닙니다.
