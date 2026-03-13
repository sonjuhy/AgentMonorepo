# Skill: ephemeral-docker-ops

## Description
이 스킬은 `Notion-Agent-Orchestrator` 모노리포 환경에서 에이전트가 Docker 컨테이너를 설계, 빌드, 테스트할 때 준수해야 하는 초경량화 및 단발성(Ephemeral) 실행 원칙을 정의합니다. 

## Principles (원리 및 근거)
1. **Zero-Idle Memory (대기 메모리 제로화)**: 대상 배포 환경은 리소스가 극히 제한된 저사양 우분투 서버입니다. 데몬(Daemon)이나 `while True` 루프 형태의 상주 프로세스를 금지하고, 스케줄러(Cron)에 의해 1회 실행 후 즉시 소멸(`--rm`)하는 구조를 채택하여 유휴 상태의 메모리 점유를 0MB로 유지합니다.
2. **Hard Resource Limits (물리적 자원 제한)**: 로컬 개발 및 테스트 환경에서도 프로덕션 환경과 동일한 128MB의 하드 메모리 제한(Cgroups)을 강제합니다. 이를 통해 서브프로세스 호출(CLI 실행) 중 발생할 수 있는 메모리 스파이크 및 OOM(Out of Memory) 현상을 사전에 검증합니다.
3. **Stateless Auth (무상태 인증)**: 컨테이너 이미지 내부에 인증 토큰(API Key, OAuth Credentials)이 하드코딩되거나 복사되는 것을 엄격히 금지합니다. 볼륨 마운트(Volume Mount)를 통한 런타임 주입 방식을 원칙으로 합니다.

## Rules (제약 사항)
- **Rule 1 (Base Image)**: Dockerfile 작성 시 반드시 `python:3.12-alpine`과 같은 초경량 베이스 이미지를 사용하십시오. Debian 기반의 `slim` 이미지는 사용하지 않습니다.
- **Rule 2 (No Daemons)**: 컨테이너의 진입점(`CMD` 또는 `ENTRYPOINT`)으로 지정되는 파이썬 스크립트 내부에 무한 대기 루프(`asyncio.sleep`의 반복 등)를 작성하지 마십시오. 스크립트는 1회 작업 완료 후 `sys.exit(0)` 또는 자연 종료되어야 합니다.
- **Rule 3 (Run Command)**: 에이전트가 터미널에서 로컬 테스트를 위해 `docker run` 명령어를 제안하거나 직접 실행할 때는 반드시 다음 옵션을 포함해야 합니다.
  - `--rm`: 실행 종료 후 컨테이너 즉시 삭제
  - `--memory="128m"`: RAM 사용량 128MB 제한
  - `-v`: 호스트의 자격 증명 경로를 읽기 전용(`:ro`)으로 마운트
- **Rule 4 (Build Context)**: 모노리포 구조이므로 Docker 빌드 컨텍스트는 항상 프로젝트의 루트(Root) 디렉토리로 설정하고, `-f` 옵션으로 에이전트별 Dockerfile 경로를 명시하십시오.

## Example: Ephemeral Docker Execution
에이전트가 로컬에서 테스트 환경을 구축하거나 명령어를 생성할 때 준수해야 하는 표준 쉘 명령어 규격입니다.

```bash
# 1. 모노리포 루트 경로에서의 이미지 빌드
docker build -t planning-agent-alpine -f agents/planning_agent/Dockerfile.alpine .

# 2. 로컬 테스트 실행 (메모리 제한 및 인증 토큰 볼륨 마운트 적용)
docker run --rm \
  --memory="128m" \
  -e NOTION_API_KEY="test_token_string" \
  -e NOTION_DATABASE_ID="test_db_string" \
  -v ~/.config/gemini:/root/.config/gemini:ro \
  planning-agent-alpine