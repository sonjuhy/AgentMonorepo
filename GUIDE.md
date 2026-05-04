# GUIDE

This project implements a multi-agent system where agents collaborate to perform complex tasks.

## Agents

The project consists of several agents, each with a specific role:

*   **Orchestra Agent (`agents/cassiopeia_agent/`):** The central orchestrator that manages task distribution, planning, and communication between other agents. It acts as the main entry point for user requests.
*   **Research Agent (`agents/research_agent/`):** Responsible for conducting research and gathering information.
*   **File Agent (`agents/file_agent/`):** Handles file operations, such as reading, writing, and managing files.
*   **Communication Agent (`agents/communication_agent/`):** Manages communication with external platforms like Slack, Discord, and Telegram.
*   **Sandbox Agent (`agents/sandbox_agent/`):** Provides a sandboxed environment for executing code safely.
*   **Schedule Agent (`agents/schedule_agent/`):** Manages scheduling and task prioritization.

## Core Libraries

*   **Shared Core (`shared_core/`):** Contains common utilities and libraries used across all agents, including logging, LLM interfaces, messaging, storage, and authentication.

## Running the Agents

### Orchestra Agent

The orchestra agent can be run as a FastAPI application.

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

Refer to the specific agent's README or documentation for instructions on how to run it. For example, to run the research agent:

```bash
python agents/research_agent/main.py
```

## Setup Wizard

The setup wizard can be run to help configure the environment:

```bash
python tools/setup_wizard.py
```

## Development Workflow

1.  **Code Structure:** Agents are located in the `agents/` directory, with core libraries in `shared_core/`.
2.  **Dependency Management:** Poetry is used for dependency management. Run `poetry install` within the respective agent's directory or at the project root if a poetry.lock exists.
3.  **Testing:** Tests are located in the `tests/` subdirectory of each agent. Use `pytest` to run tests. For example, to run tests for the orchestra agent:
    ```bash
    pytest agents/cassiopeia_agent/tests/
    ```
4.  **Code Style:** Adhere to standard Python style guides (PEP 8). Linters and formatters are configured in the project.

## Contributing

Please refer to `CONTRIBUTING.md` for more details on how to contribute to this project.

## License

This project is licensed under the Apache 2.0 License.

## Notes

*   Ensure Redis is running for message brokering.
*   Environment variables can be used for configuration.
*   This project is designed as a monorepo for easier management and development of multiple agents.

## Troubleshooting

If you encounter issues, check the agent logs, ensure dependencies are installed correctly, and verify that required services (like Redis) are running.

---
## **Previous Modifications**
*   Renamed `agents/cassiopeia_agent` to `agents/cassiopeia_agent`.
*   Updated Dockerfiles and `main.py` within `agents/cassiopeia_agent/` to reflect the new directory name and module paths.
*   Updated logger names and internal references accordingly.
*   Updated the FastAPI app title and descriptions in `agents/cassiopeia_agent/main.py`.
*   Updated `agents/cassiopeia_agent/OVERVIEW.md` to reflect the new agent name and path.
*   Updated example commands in `agents/cassiopeia_agent/Dockerfile` and `agents/cassiopeia_agent/Dockerfile.alpine` to use the new module path.
*   Updated the `state_manager.py` role check for "orchestra" to "cassiopeia".
*   Updated `README.md` with the new agent name.

## **Next Steps**
*   Rename the CI/CD workflow file.
*   Update paths within the CI/CD workflow file.
