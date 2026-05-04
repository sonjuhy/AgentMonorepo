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

### Orchestra Agent (`agents/cassiopeia_agent/`)

The orchestra agent serves as the core of the system.

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
*   Updated the `state_manager.py` role check for "orchestra" to "cassiopeia".
*   Updated `GUIDE.md` with new agent name, paths, and updated commands.

## **Next Steps**
*   Rename the CI/CD workflow file.
*   Update paths within the CI/CD workflow file.
