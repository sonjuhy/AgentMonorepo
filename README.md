# AgentMonorepo

This repository contains multiple AI agents designed to work together to perform complex tasks.

## Directory Structure

The project is structured as a monorepo, with different agents and shared libraries organized into distinct directories.

```
├───.env.example
├───.gitignore
├───.gitmessage.txt
├───agent_local_storage.db
├───docker-compose.yml
├───front_end_require.md
├───GUIDE.md
├───LICENSE
├───NOTICE
├───pytest.ini
├───README.md
├───sqlite_db.db
├───.agent
│   └───skills
│       ├───ephemeral-docker-ops
│       ├───git-commit-rule
│       ├───monorepo-cicd-router
│       ├───notion-schema-expert
│       ├───python-strict-typing
│       └───robust-pytest-strategy
├───.claude
│   ├───settings.json
│   ├───settings.local.json
│   └───worktrees
│       ├───awesome-wing
│       ├───dazzling-mirzakhani
│       ├───eager-fermat
│       ├───hardcore-chatterjee
│       └───reverent-hopper-94238b
├───.git\...
├───.github
│   └───workflows
│       ├───deploy_planning_agent.yml
│       └───deploy_slack_agent.yml
├───.pytest_cache\...
├───agents
│   ├───__init__.py
│   ├───__pycache__\...
│   ├───archive_agent
│   │   ├───__init__.py
│   │   ├───Dockerfile
│   │   ├───Dockerfile.alpine
│   │   ├───fastapi_app.py
│   │   ├───main.py
│   │   ├───models.py
│   │   ├───protocols.py
│   │   ├───redis_listener.py
│   │   ├───requirements.txt
│   │   ├───test_agent.py
│   │   ├───test_unified_agent.py
│   │   ├───unified_agent.py
│   │   ├───__pycache__\...
│   │   ├───notion
│   │   ├───obsidian
│   │   └───tests
│   ├───communication_agent
│   │   ├───__init__.py
│   │   ├───Dockerfile.alpine
│   │   ├───Dockerfile.listener
│   │   ├───listener_main.py
│   │   ├───main.py
│   │   ├───models.py
│   │   ├───protocols.py
│   │   ├───requirements.txt
│   │   ├───__pycache__\...
│   │   ├───discord
│   │   ├───slack
│   │   ├───telegram
│   │   └───tests
│   ├───file_agent
│   │   ├───__init__.py
│   │   ├───agent.py
│   │   ├───config.py
│   │   ├───interfaces.py
│   │   ├───main.py
│   │   ├───requirements.txt
│   │   ├───validator.py
│   │   ├───__pycache__\...
│   │   └───tests
│   ├───cassiopeia_agent\  # Renamed to cassiopeia_agent
│   │   ├───__init__.py
│   │   ├───admin_router.py
│   │   ├───agent_builder_handler.py
│   │   ├───agent.py
│   │   ├───app_context.py
│   │   ├───auth.py
│   │   ├───Dockerfile
│   │   ├───error_messages.py
│   │   ├───health_monitor.py
│   │   ├───intent_analyzer.py
│   │   ├───interfaces.py
│   │   ├───main.py
│   │   ├───manager.py
│   │   ├───marketplace_handler.py
│   │   ├───models.py
│   │   ├───nlu_engine.py
│   │   ├───NO_CODE_GUIDE.md
│   │   ├───OVERVIEW.md
│   │   ├───protocols.py
│   │   ├───rate_limiter.py
│   │   ├───registry.py
│   │   ├───requirements.txt
│   │   ├───sandbox_tool.py
│   │   ├───scheduler.py
│   │   ├───state_manager.py
│   │   ├───__pycache__\...
│   │   └───tests
│   ├───research_agent
│   │   ├───__init__.py
│   │   ├───agent.py
│   │   ├───config.py
│   │   ├───interfaces.py
│   │   ├───main.py
│   │   ├───pipeline.py
│   │   ├───providers.py
│   │   ├───requirements.txt
│   │   ├───__pycache__\...
│   │   └───tests
│   ├───sandbox_agent
│   │   ├───__init__.py
│   │   ├───Dockerfile
│   │   ├───main.py
│   │   ├───requirements.txt
│   │   ├───__pycache__\...
│   │   ├───sandbox
│   │   └───tests
│   └───schedule_agent
│       ├───__init__.py
│       ├───agent.py
│       ├───config.py
│       ├───interfaces.py
│       ├───main.py
│       ├───providers.py
│       ├───requirements.txt
│       ├───__pycache__\...
│       └───tests
├───aseets
│   └───img
│       ├───cassiopeia_black.png
│       └───cassiopeia_white.png
├───redis
│   ├───acl.conf
│   ├───acl.conf.tpl
│   └───entrypoint.sh
├───shared_core
│   ├───__init__.py
│   ├───agent_logger.py
│   ├───dispatch_auth.py
│   ├───__pycache__\...
│   ├───calendar
│   │   ├───interfaces.py
│   │   └───__pycache__\...
│   ├───llm
│   │   ├───__init__.py
│   │   ├───factory.py
│   │   ├───gemma_inference.py
│   │   ├───interfaces.py
│   │   ├───llm_config.py
│   │   ├───ollama_manager.py
│   │   ├───__pycache__\...
│   │   ├───providers
│   │   └───tests
│   ├───messaging
│   │   ├───__init__.py
│   │   ├───broker.py
│   │   ├───schema.py
│   │   └───__pycache__\...
│   ├───sandbox
│   │   ├───__init__.py
│   │   ├───client.py
│   │   ├───mixin.py
│   │   ├───models.py
│   │   └───__pycache__\...
│   ├───search
│   │   ├───interfaces.py
│   │   └───__pycache__\...
│   ├───storage
│   │   ├───__init__.py
│   │   ├───interfaces.py
│   │   ├───sqlite_manager.py
│   │   └───__pycache__\...
│   └───tests
│       ├───test_cassiopeia_broker.py
│       ├───test_dispatch_auth.py
│       ├───test_logging_security.py
│       └───__pycache__\...
├───tools
│   ├───__init__.py
│   ├───setup_wizard.py
│   ├───test_setup_wizard.py
│   ├───__pycache__\...
│   └───agent_builder
│       ├───__init__.py
│       ├───__main__.py
│       ├───builder.py
│       ├───cli.py
│       ├───permissions.py
│       ├───templates.py
│       ├───validator.py
│       └───...
└───venv\...

## Getting Started

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd AgentMonorepo
    ```
2.  **Set up environment variables:** Copy `.env.example` to `.env` and configure as needed.
3.  **Install dependencies:**
    *   For the whole project (if a root poetry.lock exists): `poetry install`
    *   For specific agents, navigate to their directory and run `poetry install`.

## Running the Agents

### Cassiopeia Agent (`agents/cassiopeia_agent/`)

The cassiopeia agent serves as the core of the system.

**Development Mode (local LLM):**
```bash
python agents/cassiopeia_agent/main.py --llm local
```

**Production Mode (external LLMs):**
```bash
LLM_BACKEND=chatgpt python agents/cassiopeia_agent/main.py
LLM_BACKEND=claude python agents/cassiopeia_agent/main.py
```

**Running as a module:**
```bash
python -m agents.cassiopeia_agent.main
```

### Other Agents

Each agent can be run independently. Consult their respective documentation for specific instructions. For example, to run the research agent:

```bash
python agents/research_agent/main.py
```

## Setup Wizard

The `tools/setup_wizard.py` script can assist in setting up the project environment.
```bash
python tools/setup_wizard.py
```

## Development Workflow

*   **Code Structure:** Agents are in `agents/`, shared libraries in `shared_core/`.
*   **Dependency Management:** Use Poetry. Run `poetry install` in agent directories or at the root.
*   **Testing:** Tests are in `tests/` subdirectories. Use `pytest`. Example: `pytest agents/cassiopeia_agent/tests/`
*   **Code Style:** Adhere to PEP 8. Linters and formatters are configured.

## Contributing

Please refer to `CONTRIBUTING.md` for contribution guidelines.

## License

This project is licensed under the Apache 2.0 License.

## Notes

*   Redis is required for message brokering.
*   Environment variables are used for configuration.

---
## **Previous Modifications**
*   Renamed `agents/cassiopeia_agent` to `agents/cassiopeia_agent`.
*   Updated Dockerfiles and `main.py` within `agents/cassiopeia_agent/` to reflect the new directory name and module paths.
*   Updated logger names and internal references accordingly.
*   Updated the FastAPI app title and descriptions in `agents/cassiopeia_agent/main.py`.
*   Updated `agents/cassiopeia_agent/OVERVIEW.md` to reflect the new agent name and path.
*   Updated example commands in `agents/cassiopeia_agent/Dockerfile` and `agents/cassiopeia_agent/Dockerfile.alpine` to use the new module path.
*   Updated the `state_manager.py` role check for "cassiopeia" to "cassiopeia".
*   Updated `GUIDE.md` with new agent name, paths, and updated commands.

## **Next Steps**
*   Rename the CI/CD workflow file.
*   Update paths within the CI/CD workflow file.

---
<br>

# AgentMonorepo (한국어)

이 레포지토리는 복잡한 작업을 수행하기 위해 함께 작동하도록 설계된 여러 AI 에이전트를 포함하고 있습니다.

## 디렉토리 구조

이 프로젝트는 모노리포 형태로 구성되어 있으며, 각각의 에이전트와 공통 라이브러리가 구분된 디렉토리에 정리되어 있습니다. (트리 구조는 위의 영문 섹션을 참조하세요.)

## 시작하기

1.  **저장소 클론:**
    ```bash
    git clone <repository_url>
    cd AgentMonorepo
    ```
2.  **환경 변수 설정:** `.env.example` 파일을 `.env`로 복사하고 필요에 맞게 구성합니다.
3.  **의존성 설치:**
    *   프로젝트 전체 (루트에 poetry.lock이 있는 경우): `poetry install`
    *   특정 에이전트의 경우, 해당 디렉토리로 이동하여 `poetry install`을 실행합니다.

## 에이전트 실행

### 카시오페아 에이전트 (`agents/cassiopeia_agent/`)

카시오페아(Cassiopeia) 에이전트는 시스템의 핵심 역할을 담당합니다.

**개발 모드 (로컬 LLM):**
```bash
python agents/cassiopeia_agent/main.py --llm local
```

**운영 모드 (외부 LLM):**
```bash
LLM_BACKEND=chatgpt python agents/cassiopeia_agent/main.py
LLM_BACKEND=claude python agents/cassiopeia_agent/main.py
```

**모듈로 실행:**
```bash
python -m agents.cassiopeia_agent.main
```

### 다른 에이전트들

각 에이전트는 독립적으로 실행될 수 있습니다. 구체적인 실행 방법은 각 에이전트의 문서를 참조하세요. 예를 들어, 리서치 에이전트를 실행하려면:

```bash
python agents/research_agent/main.py
```

## 설정 마법사 (Setup Wizard)

프로젝트 환경 설정을 돕기 위해 `tools/setup_wizard.py` 스크립트를 사용할 수 있습니다.
```bash
python tools/setup_wizard.py
```

## 개발 워크플로우

*   **코드 구조:** 에이전트들은 `agents/`에, 공통 라이브러리는 `shared_core/`에 위치합니다.
*   **의존성 관리:** Poetry를 사용합니다. 에이전트 디렉토리 또는 루트에서 `poetry install`을 실행하세요.
*   **테스트:** 테스트는 각 `tests/` 하위 디렉토리에 있습니다. `pytest`를 사용하세요. 예: `pytest agents/cassiopeia_agent/tests/`
*   **코드 스타일:** PEP 8을 준수합니다. Linter와 Formatter가 구성되어 있습니다.

## 기여하기

기여 가이드라인은 `CONTRIBUTING.md`를 참조하세요.

## 라이선스

이 프로젝트는 Apache 2.0 License 조건에 따라 배포됩니다.

## 참고 사항

*   메시지 브로커링을 위해 Redis가 필요합니다.
*   환경 변수를 사용하여 시스템을 구성합니다.

---
## **이전 수정 사항**
*   `agents/cassiopeia_agent` 디렉토리명을 현재의 이름으로 변경했습니다.
*   새로운 디렉토리 이름과 모듈 경로를 반영하여 `agents/cassiopeia_agent/` 내부의 Dockerfile과 `main.py`를 업데이트했습니다.
*   로거 이름 및 내부 참조 경로를 일치되게 업데이트했습니다.
*   `agents/cassiopeia_agent/main.py`의 FastAPI 앱 제목 및 설명을 수정했습니다.
*   에이전트 이름 및 경로 변경 사항을 반영하여 `agents/cassiopeia_agent/OVERVIEW.md`를 수정했습니다.
*   새로운 모듈 경로를 사용하도록 Dockerfile들의 예시 명령어를 업데이트했습니다.
*   `state_manager.py`의 역할 확인 조건("cassiopeia")을 업데이트했습니다.
*   새로운 에이전트 이름과 경로, 업데이트된 명령어를 `GUIDE.md`에 반영했습니다.

## **다음 단계**
*   CI/CD 워크플로우 파일 이름 변경.
*   CI/CD 워크플로우 내 경로 업데이트.
