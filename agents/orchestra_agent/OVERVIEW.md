# 🎼 Orchestra Agent (오케스트라 에이전트) 개요 및 사용 가이드

이 저장소에 구축된 **오케스트라 에이전트(Orchestra Agent)** 시스템은 다수의 특수 목적 AI 에이전트들을 하나의 거대한 지휘 체계로 묶어, 사용자의 복잡한 자연어 요청을 처리하는 **멀티 에이전트 프레임워크(Multi-Agent Framework)**입니다. 

기존에 터미널 기반의 `Gemini CLI`(레거시) 방식에서 진화하여, 현재는 완전한 비동기 분산 시스템(Redis 기반)으로 작동합니다. 제공하는 핵심 기능들과 사용 방법을 아래에 정리합니다.

---

## 🌟 1. 오케스트라 시스템의 핵심 기능 (Core Capabilities)

*   **중앙 지휘 통제 (Orchestration & NLU)**
    *   사용자가 슬랙(Slack)이나 API로 "내일 오후 3시 회의 일정 잡고, 관련 자료 검색해서 노션에 정리해 줘"라고 자연어로 말하면, **오케스트라 에이전트**의 NLU(자연어 이해) 엔진이 이를 분석합니다.
    *   단일 작업인지 복합 작업(Multi-step)인지 판단하여, 계획(Plan)을 세우고 알맞은 하위 에이전트들에게 순차적/병렬적으로 작업을 분배(Dispatch)합니다.
*   **플러그인 방식의 무한한 확장성 (Agent Registry & Marketplace)**
    *   새로운 기능이 필요하면 `agent-builder` 도구를 통해 에이전트를 쉽게 생성할 수 있습니다.
    *   에이전트가 켜질 때 자신을 오케스트라에 자동 등록(Register)하고, 주기적으로 살아있음을 알리는 하트비트(Heartbeat)를 보냅니다.
*   **보안 격리 및 샌드박스 (Sandboxing)**
    *   사용자가 파이썬이나 자바스크립트 코드를 실행해 달라고 요청하면, 호스트 서버가 아닌 Docker나 Firecracker VM 같은 **완벽히 격리된 환경(Sandbox Agent)**에서 코드를 실행하여 시스템을 안전하게 보호합니다.
*   **상태 및 기억 유지 (State & Memory Management)**
    *   이전 대화 맥락, 사용자의 선호 스타일, 개별 사용자의 LLM API 키(Gemini, Claude 등)를 대칭키(AES)로 암호화하여 DB(SQLite)와 캐시(Redis)에 안전하게 관리합니다.

---

## 🤖 2. 사용 가능한 특수 목적 에이전트들 (Available Agents)

오케스트라의 지휘를 받아 실제 작업을 수행하는 일꾼들입니다.

1.  **🗣️ Communication Agent (소통 에이전트)**
    *   Slack, Discord, Telegram 등 메신저 플랫폼과 연결되어 사용자의 입력을 받고, 봇의 답변이나 진행 상황을 스레드(Thread)로 전달합니다.
2.  **🔍 Research Agent (리서치 에이전트)**
    *   "최신 AI 트렌드 조사해 줘" 같은 요청을 받으면, Perplexity나 Google 검색을 통해 최신 정보를 수집하고 구조화된 보고서를 작성합니다.
3.  **📚 Archive Agent (아카이브 에이전트)**
    *   조사된 내용이나 대화 기록을 사용자의 Notion(노션) 데이터베이스나 Obsidian(옵시디언) 로컬 볼트에 영구적으로 저장하고 검색합니다.
4.  **🗓️ Schedule Agent (일정 에이전트)**
    *   Google Calendar API와 연동하여 사용자의 일정을 조회하거나 새로운 이벤트를 캘린더에 추가합니다.
5.  **💻 Coding & Sandbox Agent (코딩 에이전트)**
    *   코드를 작성, 리뷰, 리팩토링(Coding Agent)하고, 작성된 코드를 안전한 격리 환경에서 직접 실행(Sandbox Agent)하여 결과(에러, 출력값)를 반환합니다.
6.  **📂 File Agent (파일 에이전트)**
    *   시스템 내의 로컬 파일을 읽고, 쓰고, 검색하는 등의 안전한 파일 시스템 I/O를 담당합니다.

---

## 🚀 3. 시스템 사용 방법 (How to Use)

사용자의 기술 수준과 목적에 따라 세 가지 방식으로 시스템과 상호작용할 수 있습니다.

### A. 일반 사용자 입장 (가장 쉬운 방법 - 메신저 사용)
1.  **Slack (또는 Discord) 접속:** 시스템이 연동된 슬랙 채널에 들어갑니다.
2.  **자연어 멘션:** 봇을 멘션하여 자연어로 명령을 내립니다.
    *   *예시:* `@OrchestraBot 최근 3일간의 이메일을 요약해서 내 노션 '업무 일지' 페이지에 저장해 줘.`
3.  **결과 확인:** 오케스트라가 리서치 에이전트와 아카이브 에이전트를 조종하여 작업을 수행한 뒤, 슬랙 스레드로 완료 메시지와 결과 링크를 보내줍니다.

### B. 프론트엔드/UI 개발자 입장 (API 연동)
별도의 웹 대시보드나 UI를 개발 중이라면, 오케스트라가 제공하는 REST API를 호출합니다. (최근 업데이트된 `UI_INTEGRATION_API_UPDATE.md` 참조)
1.  **태스크 전송:** `POST http://localhost:8001/tasks` 엔드포인트에 사용자의 텍스트를 JSON으로 보냅니다.
2.  **실시간 상태 확인:** 응답받은 `task_id`를 가지고 `GET /tasks/{task_id}?include_logs=true`를 폴링하여 화면에 "검색 중...", "노션에 쓰는 중..." 등 실시간 진행 상태를 보여줍니다.
3.  **작업 취소:** 작업이 오래 걸리면 `POST /tasks/{task_id}/cancel`을 호출해 즉시 중단합니다.

### C. 백엔드 시스템 관리자 입장 (CLI 및 Docker)
1.  **서버 전체 실행:**
    ```bash
    # Redis, Ollama, 오케스트라, 하위 에이전트들을 한 번에 실행
    docker-compose up -d
    ```
2.  **오케스트라 에이전트 단독 실행 (개발 모드):**
    ```bash
    # 사용할 LLM 모델(gemini, claude, local 등)을 지정하여 실행
    python -m agents.orchestra_agent.main --llm gemini
    ```
3.  **에이전트 로그 모니터링:** 
    Redis 큐(`agent:orchestra:tasks`, `orchestra:results:*`)를 모니터링하거나, 백엔드 DB의 `agent_logs` 테이블을 통해 전체 시스템이 어떻게 흘러가는지 관제합니다.

---

요약하자면, 이 시스템은 **"복잡한 일을 알아서 쪼개고, 전문가(에이전트)들에게 나눠준 뒤, 결과를 취합해 주는 똑똑한 AI 비서실장"**이라고 볼 수 있습니다!
