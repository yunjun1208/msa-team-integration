# 비용 절감을 위한 종료와 다음 날 복원

현재 계정 `256187519952`, 서울 리전, `msa-final-eks` 전용 절차입니다.
아래 스크립트는 기존 회원·상품·주문 데이터와 이미지, 모니터링 저장소를 보존하는
**부분 종료**입니다. 전체 `terraform destroy` 또는 상태 저장소 삭제를 함께 실행하지 마세요.

## 보존하는 항목

- Terraform 상태 버킷과 원격 상태, CloudTrail 로그 S3, 상품 이미지 S3
- ECR 저장소와 현재 배포 이미지
- 수동 RDS 스냅샷 (애플리케이션 쓰기를 중단한 뒤 생성하고 완료 확인)
- 모니터링 EBS 3개: Grafana, Prometheus, Alertmanager의 원본 볼륨
- SNS/SQS, 메일 중복 방지 DynamoDB, ACM 인증서와 인증 CNAME
- 로컬 `.overnight/recovery.dpapi`: 저장소 읽기 토큰, 앱 키, 관리자 bootstrap Secret,
  PV/PVC 연결 정보, Terraform 상태 사본을 Windows DPAPI로 암호화

보존 항목의 저장·요청 비용은 남습니다. EKS, EC2 노드, RDS 인스턴스,
ALB와 NAT Gateway 등 실행 비용이 큰 인프라를 제거합니다.

## 오늘

1. 이 변경을 main에 커밋·푸시합니다. 이후 복원이 끝날 때까지 릴리스 PR을 병합하지 않습니다.
2. GitHub repository variables의 `ENABLE_AWS_PUBLISH`, `ENABLE_DEPLOY_CHECKS`를 `false`로
   바꾸고 진행 중인 관련 GitHub Actions가 종료됐는지 확인합니다.
3. 프로젝트 디렉터리에서 다음 명령으로 준비합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ops/Manage-Overnight.ps1 -Action Prepare
```

Prepare는 계정·클러스터·Git main·복원 자격증명·모니터링 볼륨을 확인하고,
암호화 백업을 다시 읽어 검증하며, 인프라 삭제 **계획만** 생성합니다.
보존 리소스 삭제가 계획에 있으면 중단합니다. 이 단계에서는 서비스를 중지하지 않습니다.
준비에 실패하면 백업을 임의로 삭제하지 말고 오류부터 확인합니다.

4. `PREPARED`와 삭제 계획을 확인한 뒤 다음 명령으로 종료합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ops/Manage-Overnight.ps1 -Action Stop
```

Stop은 DNS 별칭 제거 → GitOps 중지 → PV Retain 변경 → 앱 쓰기 중단 →
RDS 스냅샷 완료 확인 → 앱·Ingress 제거 및 ALB 삭제 대기 → Kubernetes 구성 제거 →
보존 대상 제외 인프라 삭제 순서로 진행합니다. 이미 승인한 종료를 자동 실행합니다.
스냅샷 실패·계획 보호장치 실패 시 인프라 삭제로 넘어가지 않습니다.
중간 실패 시 오류를 확인하고 동일 Stop 명령을 재실행합니다.
`STOPPED`가 출력되지 않으면 종료 완료로 간주하지 않습니다.

`.overnight`와 로컬 `terraform/*.tfvars`, `terraform-k8s/*.tfvars`를 보관합니다.
DPAPI 백업은 **같은 Windows 컴퓨터·사용자**로만 복호화할 수 있습니다.
프로젝트/사용자 프로필을 삭제하거나 다른 PC로 옮기지 마세요.

## 내일: 실행 명령 하나

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ops/Manage-Overnight.ps1 -Action Resume
```

RDS 스냅샷 존재 확인 → 현재 PC IPv4 /32 접근 설정 → AWS 인프라 복원 → EKS 연결 →
네임스페이스/스토리지 준비 → 보존 EBS/PVC 연결 → 앱 키·관리자 설정 복원 →
관리 도구 설치 → DB Secret 준비 → 앱 동기화 → DNS 별칭 복원 → HTTPS/API 검사 순서입니다.
현재 PC IPv4만 /32로 추가하며 공개 API를 전체 인터넷에 개방하지 않습니다.

실패하면 해당 단계에서 멈춥니다. 오류 확인 후 Resume을 다시 실행할 수 있습니다.
새 Argo CD의 초기 관리자 비밀번호는 새로 생성될 수 있습니다.
Grafana 데이터/설정은 보존 EBS를 재연결합니다.
복원 선택은 Git에서 제외된 `terraform/overnight-phase.auto.tfvars.json`에 유지합니다.

마지막 `RESUMED AND VERIFIED` 후 로그인 및 기존 주문을 직접 확인합니다.
그다음 GitHub variables 두 값을 다시 `true`로 바꾸고 Verify approved deployment를 실행합니다.

## 검증 범위

Terraform validate, 모의 Terraform 테스트, PowerShell 구문 검사와 합성 삭제 계획에 대한
보호장치 테스트를 수행했습니다. 실제 전체 종료/재구축은 아직 이 환경에서 완료하지 않았습니다.
AWS API·용량·차트 다운로드 상태에 따라 중간 조치가 필요할 수 있습니다.
이 스크립트는 현재 한 번의 overnight 복원용이며 여러 날짜의 백업 순환 관리는 포함하지 않습니다.
