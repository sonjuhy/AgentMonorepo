# Skill: monorepo-cicd-router

## Description
이 스킬은 `Notion-Agent-Orchestrator` 모노리포 환경에서 에이전트가 GitHub Actions 기반의 CI/CD 파이프라인(YAML)을 작성하거나 수정할 때 적용되는 원칙을 정의합니다. 대상 인프라는 리소스가 제한된 우분투 서버이며, GHCR(GitHub Container Registry)을 경유하는 SSH 원격 배포 방식을 사용합니다.

## Principles (원리 및 근거)
1. **Selective Deployment (선택적 배포 최적화)**: 모노리포의 핵심은 변경된 모듈만 격리하여 빌드하는 것입니다. 특정 에이전트(예: `planning_agent`)의 코드나 공통 코어(`shared_core`)가 수정되었을 때만 해당 에이전트의 워크플로우가 트리거되도록 경로 필터링(Path Filtering)을 강제하여 빌드 자원 낭비를 막습니다.
2. **Offloaded Build (빌드 부하 분산)**: 저사양 우분투 서버에서 직접 `docker build`를 수행하면 CPU 점유율이 치솟아 기존 서비스에 영향을 줍니다. 따라서 이미지 빌드 과정은 GitHub Actions의 자체 가상 환경(Runner)에서 처리하고 완성된 이미지를 GHCR에 푸시한 뒤, 서버는 단순히 `docker pull`만 수행하도록 역할을 분리합니다.
3. **Immutability & Pruning (불변성 및 자동 정리)**: 새로운 이미지가 배포될 때마다 기존 이미지 태그를 덮어쓰고, 서버의 저장 공간 확보를 위해 연결이 끊긴 구형 이미지(Dangling images)를 자동 삭제(`prune`)하는 루틴을 반드시 포함합니다.

## Rules (제약 사항)
- **Rule 1 (File Location & Naming)**: 모든 배포 파이프라인 파일은 `.github/workflows/` 디렉토리에 위치해야 하며, 파일명은 `deploy_<agent_name>.yml` 형식을 엄격히 따르십시오.
- **Rule 2 (Path Triggering)**: `on: push` 트리거 작성 시 반드시 `paths` 속성을 명시하십시오. 포함되어야 할 경로는 다음과 같습니다.
  - 해당 에이전트의 소스 디렉토리 (예: `agents/planning_agent/**`)
  - 공통 의존성 디렉토리 (`shared_core/**`)
  - 파이프라인 파일 자체 (`.github/workflows/deploy_planning_agent.yml`)
- **Rule 3 (Registry & Context)**: Docker 이미지 빌드 시 `docker/build-push-action`을 사용하고, 모노리포 구조이므로 `context`는 최상단 루트(`.`)로 설정하되 `file` 속성에 개별 에이전트의 Dockerfile 경로를 정확히 지정하십시오.
- **Rule 4 (SSH Deployment)**: `appleboy/ssh-action`을 사용하여 우분투 서버에 접속할 때, 다음 3가지 명령어가 순서대로 실행되도록 스크립트를 구성하십시오.
  1. `docker login` (GHCR 인증)
  2. `docker pull` (최신 이미지 다운로드)
  3. `docker image prune -f` (잔여 찌꺼기 이미지 정리)

## Example: CI/CD Workflow Template
에이전트가 새로운 에이전트 배포 파이프라인을 생성할 때 출력해야 하는 표준 YAML 템플릿입니다.

```yaml
name: Deploy [Agent Name]

on:
  push:
    branches: [main]
    paths:
      - 'agents/[agent_name]/**'
      - 'shared_core/**'
      - '.github/workflows/deploy_[agent_name].yml'

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
          
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: ./agents/[agent_name]/Dockerfile.alpine
          push: true
          tags: ghcr.io/${{ github.repository }}-[agent_name]:latest
          
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: |
            echo ${{ secrets.GITHUB_TOKEN }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin
            docker pull ghcr.io/${{ github.repository }}-[agent_name]:latest
            docker image prune -f