# OVERVIEW OF THE CASSIOPEIA AGENT

This document outlines the core functionality, architecture, and usage of the cassiopeia agent.

## Functionality

The cassiopeia agent serves as the central nervous system of our multi-agent system. Its primary responsibilities include:

1.  **Intent Recognition and Analysis:** Understanding user requests and breaking them down into actionable tasks.
2.  **Task Cassiopeiation:** Planning and sequencing tasks for various specialized agents.
3.  **Agent Coordination:** Managing the lifecycle and communication between different agents.
4.  **Information Synthesis:** Aggregating and presenting results from multiple agents.
5.  **Context Management:** Maintaining conversational context and state.
6.  **LLM Interaction:** Leveraging large language models for various sub-tasks, including planning, analysis, and response generation.

## Architecture

The agent follows a modular design, with distinct components responsible for specific functions. Key modules include:

*   **`main.py`:** Entry point and main application logic, including FastAPI server setup.
*   **`manager.py`:** Handles the core cassiopeiation logic, agent lifecycle, and communication.
*   **`nlu_engine.py`:** Processes natural language understanding tasks.
*   **`state_manager.py`:** Manages the state of the system and ongoing tasks.
*   **`health_monitor.py`:** Monitors the health and responsiveness of other agents.
*   **`app_context.py`:** Provides application-wide context and dependencies.
*   **`auth.py`:** Handles authentication and authorization.
*   **`registry.py`:** Manages the registration and discovery of agents.
*   **`marketplace_handler.py`:** Interacts with the agent marketplace.
*   **`sandbox_tool.py`:** Manages sandboxed execution environments.
*   **`rate_limiter.py`:** Implements rate limiting for agent interactions.
*   **`error_messages.py`:** Centralizes error message definitions.
*   **`models.py`:** Defines data structures and Pydantic models used throughout the agent.

## Usage

### Running the Cassiopeia Agent

The agent can be run as a FastAPI application.

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

### Key Features and Commands

*   **Intent Analysis:** The agent analyzes user intents to determine the best course of action.
*   **Agent Dispatch:** Based on the analyzed intent, the agent dispatches requests to appropriate specialized agents.
*   **LLM Integration:** The agent integrates with various LLM providers (local, ChatGPT, Claude, Gemini) for advanced reasoning capabilities.
    *   Example command: `python -m agents.cassiopeia_agent.main --llm gemini`

## Contribution

Please refer to the main project's `CONTRIBUTING.md` for details on how to contribute.

## License

This project is licensed under the Apache 2.0 License.

## Notes

*   The agent relies on Redis for message brokering. Ensure Redis is running and accessible.
*   Environment variables can be used to configure LLM backends and other settings.
*   The `agents/cassiopeia_agent` directory contains the primary logic for the cassiopeiator.

---
<br>

# 카시오페아 에이전트 개요 (Korean)

이 문서는 카시오페아(Cassiopeia) 에이전트의 핵심 기능, 아키텍처 및 사용 방법을 간략히 설명합니다.

## 주요 기능

카시오페아 에이전트는 멀티 에이전트 시스템의 중앙 신경망 역할을 수행합니다. 주요 책임은 다음과 같습니다:

1.  **의도 파악 및 분석:** 사용자의 요청을 이해하고 실행 가능한 태스크 단위로 분해합니다.
2.  **태스크 오케스트레이션 (Task Cassiopeiation):** 다양한 전문 에이전트가 수행할 태스크의 계획을 수립하고 순서를 정합니다.
3.  **에이전트 조정 (Agent Coordination):** 다른 에이전트들의 생명주기 및 상호 간의 통신을 관리합니다.
4.  **정보 종합 (Information Synthesis):** 여러 에이전트로부터 받은 결과를 취합하고 정리하여 제공합니다.
5.  **컨텍스트 관리 (Context Management):** 사용자와의 대화 맥락과 시스템 상태를 유지합니다.
6.  **LLM 상호작용:** 계획 수립, 분석, 응답 생성 등 다양한 하위 작업에 대형 언어 모델(LLM)을 활용합니다.

## 아키텍처

에이전트는 각기 특정 기능을 담당하는 여러 컴포넌트로 나뉘는 모듈형 설계를 따릅니다. 주요 모듈은 다음과 같습니다:

*   **`main.py`:** 진입점(Entry point)이자 FastAPI 서버 설정 등을 포함하는 메인 애플리케이션 로직.
*   **`manager.py`:** 핵심 오케스트레이션 로직, 에이전트 생명주기 관리 및 통신을 담당.
*   **`nlu_engine.py`:** 자연어 이해(NLU) 관련 작업을 처리.
*   **`state_manager.py`:** 시스템의 상태와 진행 중인 태스크들을 관리.
*   **`health_monitor.py`:** 연결된 다른 에이전트들의 상태(Health)와 응답성을 모니터링.
*   **`app_context.py`:** 애플리케이션 전반에 걸친 컨텍스트 및 의존성을 제공.
*   **`auth.py`:** 인증 및 권한 부여를 처리.
*   **`registry.py`:** 에이전트 등록 및 탐색을 관리.
*   **`marketplace_handler.py`:** 에이전트 마켓플레이스와의 상호작용을 담당.
*   **`sandbox_tool.py`:** 코드가 격리된 샌드박스 환경에서 실행될 수 있도록 관리.
*   **`rate_limiter.py`:** 에이전트 상호작용에 대한 속도 제한(Rate limiting)을 구현.
*   **`error_messages.py`:** 에러 메시지 정의를 한 곳에 중앙화.
*   **`models.py`:** 시스템 전반에서 사용되는 데이터 구조와 Pydantic 모델을 정의.

## 사용 방법

### 카시오페아 에이전트 실행

해당 에이전트는 FastAPI 애플리케이션으로 실행 가능합니다.

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

### 주요 특징 및 명령어

*   **의도 분석:** 사용자 의도를 분석하여 가장 최적의 작업 방향을 결정합니다.
*   **에이전트 디스패치:** 파악된 의도를 기반으로 적절한 전문 에이전트에게 요청을 디스패치(전달)합니다.
*   **LLM 연동:** 고도의 추론 능력을 위해 다양한 LLM 제공업체(Local, ChatGPT, Claude, Gemini)와 연동됩니다.
    *   예시 명령어: `python -m agents.cassiopeia_agent.main --llm gemini`

## 기여하기

프로젝트 기여 방법에 대한 자세한 내용은 프로젝트 루트의 `CONTRIBUTING.md`를 참조하세요.

## 라이선스

이 프로젝트는 Apache 2.0 라이선스 조건에 따라 배포됩니다.

## 참고 사항

*   이 에이전트는 메시지 브로커링을 위해 Redis에 의존합니다. Redis 서버가 실행 중이며 접근 가능한지 확인하세요.
*   LLM 백엔드 및 기타 설정은 환경 변수를 사용하여 구성할 수 있습니다.
*   오케스트레이터의 핵심 로직은 `agents/cassiopeia_agent` 디렉토리에 포함되어 있습니다.
