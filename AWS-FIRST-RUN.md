# 본인 AWS 계정 최초 구축

계정 256187519952 / 서울 ap-northeast-2 / Route53 aws-cisco.com / 새 저장소 yunjun1208/msa-team-integration.
쇼핑몰 server.aws-cisco.com, 관리 화면 argocd.aws-cisco.com / grafana.aws-cisco.com을 사용합니다.
AWS 자원 생성은 아직 수행하지 않았습니다. EKS·EC2·RDS·NAT·ALB 및 로그 비용이 발생합니다.

## 1. 프로젝트 폴더와 새 저장소

짧은 경로(예: C:\msa-team)에 이 프로젝트를 풉니다. PowerShell을 열고 폴더로 이동합니다.
기존 ZIP의 state/tfvars/백업을 이 폴더에 복사하지 마세요.

```powershell
Set-Location C:\msa-team
# 실제 압축을 푼 프로젝트 폴더를 지정하세요.
powershell -ExecutionPolicy Bypass -File .\Upload-NewRepo.ps1
```

GitHub 인증 창은 본인이 완료합니다. Git 작성자 미설정이면 다음을 실행하고 `git commit`, `git push -u origin main`을 다시 실행합니다.

```powershell
git config user.name "yunjun1208"
git config user.email "본인 GitHub에 등록한 이메일"
```

첫 push는 테스트를 실행합니다. ENABLE_AWS_PUBLISH를 설정하기 전에는 AWS 게시를 하지 않습니다. 테스트 실패는 Actions 로그로 수정하고 진행하세요.
GitHub에서 이 저장소 Actions → Check AWS OIDC subject → Run workflow(main)를 실행합니다. 로그의 subject만 확인합니다. 토큰은 출력하지 않습니다.

## 2. 내 설정 준비 (조회 + 로컬 파일 생성)

EKS API 허용 IP는 현재 PC의 공인 IPv4에 /32를 붙입니다. 공유기 내부 IP가 아닙니다. 아래 값은 실제 값으로 교체합니다.

```powershell
.\Prepare-Aws.ps1 -AlertEmail '본인메일@example.com' -AdminCidr '본인공인IPv4/32' -GithubOidcSubject '앞 단계 로그의 subject' -SesSenderEmail 'SES 발신자메일@example.com'
```

스크립트는 default 프로필의 계정·공개 영역·기존 GitHub OIDC를 조회하고 tfvars를 생성합니다. 기존 파일은 덮어쓰지 않습니다. 세션 ARN 사용자는 별도 IAM role ARN 설정이 필요합니다.
SES 발신자 주소는 기존 인증 여부를 SES 콘솔에서 확인합니다. 메일 인증 전에는 customer_email_enabled=false를 유지합니다. 미인증이면 SES에서 인증을 요청하고 본인이 승인합니다.

## 3. state 버킷 → AWS 인프라

기존 IAM/ECR/VPC/로그/Route53 레코드는 이번 조회에서 모두 확인한 것이 아닙니다. plan과 AWS 오류에서 충돌하면 멈추고 검토합니다. 기존 OIDC는 재사용하며 기존 자원을 임의로 삭제하지 않습니다.

```powershell
terraform -chdir=terraform-state-bootstrap init
terraform -chdir=terraform-state-bootstrap validate
terraform -chdir=terraform-state-bootstrap plan
terraform -chdir=terraform-state-bootstrap apply
terraform -chdir=terraform init
terraform -chdir=terraform validate
terraform -chdir=terraform plan
terraform -chdir=terraform apply
aws eks update-kubeconfig --region ap-northeast-2 --name msa-final-eks --profile default
kubectl get nodes
```

plan에 삭제나 교체가 표시되면 예상한 새 환경인지 확인 후 중단·검토하세요. apply는 사람이 plan을 확인하고 승인합니다. state bootstrap local state는 비공개 백업하고 Git에 올리지 않습니다.
기본 노드 구성은 AZ 두 곳에 t3.small 4개(최대 5개)입니다. 상위 node_desired_size 변수와 달리 실제 zonal pool 설정이 사용됩니다. 리소스 변경은 메모리 요청량을 확인 후 진행하세요.
기본 EKS/MySQL 버전은 코드의 값이며 계정/리전의 지원 여부를 plan/apply 전에 확인해야 합니다.

## 4. 클러스터 도구와 Secret

아래 Prepare-Secrets는 같은 PowerShell 프로세스에서 실행해야 Terraform에 환경변수가 전달됩니다. 별도 powershell -File로 실행하지 마세요.

```powershell
.\terraform-k8s\Prepare-Secrets.ps1
terraform -chdir=terraform-k8s init
terraform -chdir=terraform-k8s validate
terraform -chdir=terraform-k8s plan
terraform -chdir=terraform-k8s apply
kubectl wait externalsecret/database-credentials -n soldesk --for=condition=Ready --timeout=180s
```

Private 저장소 읽기 토큰은 입력 프롬프트에서만 입력합니다. 이 저장소에만 Contents read 권한을 가진 토큰을 사용하고 채팅·파일에 붙이지 마세요. 앱 sync는 계속 false입니다.

## 5. 최초 이미지 게시

Docker Desktop 실행, JDK17/JAVA_HOME, Git Bash, Node, Python이 필요합니다.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
.\app\msa\scripts\Build-Images.ps1 -ImageTag 'integration-v1' -Push
git diff -- app/msa/kustomization.yaml
git add app/msa/kustomization.yaml
git commit -m "Publish initial integration images"
git push
```

스크립트는 독립 테스트 후 이미지 5개를 게시하고 배포 태그를 바꿉니다. ECR immutable 태그이므로 재빌드 때는 integration-v2 등 새 태그를 사용하세요.

## 6. 앱 활성화 → DNS

terraform-k8s/terraform.tfvars의 enable_app_sync=true로 바꾼 뒤 같은 PowerShell에서 plan/apply합니다. 관리자 계정 Secret도 준비합니다.

```powershell
.\app\msa\Prepare-Admin.ps1
terraform -chdir=terraform-k8s plan
terraform -chdir=terraform-k8s apply
kubectl get deployments,pods,ingress -n soldesk
```

Argo의 앱 revision이 새 저장소 main인지, 5개 Deployment가 Ready인지 확인합니다. 외부 ALB가 생성된 후 terraform/terraform.tfvars의 enable_website_dns=true로 바꾸고 infra plan/apply합니다.
기존 server 레코드가 남았다면 오류를 보고 멈추고 import/교체 여부를 확인하세요.
https://server.aws-cisco.com에서 회원가입·로그인·상품 등록·주문·재고·주문 내역을 확인합니다. 로컬 smoke.py는 localhost 전용이므로 AWS에 그대로 실행하지 않습니다.

## 7. 관리 화면·메일·자동 게시

관리 화면: k8s tfvars의 enable_management_ingress=true → k8s plan/apply → infra enable_management_dns=true → infra plan/apply.
메일: SES 인증과 sandbox 수신자 인증 확인 → customer_email_enabled=true → infra plan/apply → 실제 주문·수신·DLQ 확인.
자동 게시: AWS_ROLE_TO_ASSUME 변수에 terraform output github_actions_role_arn 값을 등록한 뒤 ENABLE_AWS_PUBLISH=true를 설정합니다. GitHub Actions의 PR 생성 허용 및 배포 PR 검토가 필요합니다. 배포 조회는 별도 역할/네트워크 준비 후 ENABLE_DEPLOY_CHECKS를 설정합니다.

## 확인 범위

이번 패키지는 계정/도메인/저장소 설정 수정본입니다. AWS apply·실제 주문·메일 수신 완료본이 아닙니다. 기존 로컬 FIX-REPORT.md의 결과는 이전 로컬 패키지 기준이며, 이번 검사 결과는 AWS-PREP-REPORT.md를 보세요.
