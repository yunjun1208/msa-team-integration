# AWS 배포 준비 수정 결과 (2026-10-19)

## 적용한 설정

- 계정 256187519952, 서울 ap-northeast-2.
- 기존 공개 Hosted Zone Z0919221R8VC8SHAV8CP / aws-cisco.com.
- server.aws-cisco.com, argocd.aws-cisco.com, grafana.aws-cisco.com.
- 새 GitHub 저장소 yunjun1208/msa-team-integration, EKS msa-final-eks.
- ECR/IAM/IRSA/SNS/state backend/운영 스크립트/테스트에서 이전 계정 참조 변경.
- 신규 전용 state 버킷 final-tfstate-256187519952-ap-northeast-2. state 이전이나 기존 자원 삭제는 하지 않음.
- 기존 GitHub OIDC provider 재사용 입력 추가. 게시·조회 역할이 같은 실제 subject를 사용하도록 통일.
- 최초 push의 AWS 게시를 ENABLE_AWS_PUBLISH 변수로 보류. OIDC subject 조회 workflow 추가.
- Prepare-Aws.ps1로 계정/공개 영역 확인, OIDC 재사용 조회 및 개인 tfvars 생성.
- Upload-NewRepo.ps1로 새 저장소에만 push하며 비밀값/state 경로를 차단. 강제 push하지 않음.

## 이번에 수행한 검사

- Python 회귀 테스트 18개 통과.
- 프런트엔드 Node 테스트 7개 통과.
- PowerShell 전체 파일 구문 검사 오류 0.
- Prepare-Aws.ps1을 가짜 AWS 응답으로 실행하여 tfvars 12개 항목이 각 줄로 생성되는지 확인. 실제 AWS 조회/변경을 수행한 검사가 아님.
- Terraform fmt 검사 통과.
- Terraform init -backend=false를 시도했으나 provider 다운로드 임시 파일 checksum의 Access denied로 중단. validate/plan 성공으로 보고하지 않음.

## 남은 검증

GitHub 인증/업로드, 실제 CI, Terraform init/validate/plan, 잔여 IAM/ECR/네트워크/로그/레코드와 이름 충돌, EKS/MySQL 버전 지원, 실제 배포·주문·재고·이메일은 확인 전입니다.
AWS 자원 생성이나 기존 GitHub 변경은 이번 작업에서 하지 않았습니다. AWS-FIRST-RUN.md 순서대로 진행하며 오류가 나오면 다음 단계로 넘어가지 마세요.
과거 문서의 운영 성공 기록은 팀원 원본 프로젝트의 기록이며, 이 계정에서 통합본이 검증됐다는 뜻이 아닙니다.
