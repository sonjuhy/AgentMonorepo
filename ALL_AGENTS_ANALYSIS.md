# AgentMonorepo 통합 에이전트 분석 보고서

본 문서는 `AgentMonorepo` 내에서 동작하는 전체 에이전트 시스템에 대한 상세 아키텍처 및 구현 분석 보고서입니다. 각 에이전트가 시스템 내에서 담당하는 역할, 기능, 동작 시퀀스, 예외 처리, 관련 코드 및 한계점을 다룹니다.

> **최종 갱신**: 2026-04-22 기준 실제 코드 분석 반영

---

## 1. Orchestra Agent (오케스트라 에이전트)
* **해당 코드**: `agents/orchestra_agent/` (`main.py`, `manager.py`, `nlu_engine.py`, `state_manager.py`, `health_monitor.py`, `marketplace_handler.py`, `agent_builder_handler.py`, `registry.py`, `models.py`, `protocols.py`, `interfaces.py`, `admin_router.py`, `app_context.py`, `intent_analyzer.py`)
* **목적**: 시스템의 중앙 지휘자(Conductor). 사용자의 자연어 요청을 분석하여 시스템 내 어떤 하위 에이전트가 작업을 수행할지 결정하고 작업의 생명주기를 관리합니다.
* **기능**:
  * **NLU 기반 라우팅**: `shared_core.llm` 팩토리를 통해 LLM 공급자(Gemini, Claude, Local)를 선택하여 사용자 의도를 분석하고, `single` / `multi_step` / `clarification` / `direct_response` 4가지 유형으로 분류합니다.
  * **다중 플랫폼 라우팅**: `task.source` 필드(`slack` / `discord` / `telegram`)에 따라 플랫폼별 통신 큐(`agent:communication:tasks`, `agent:communication:discord:tasks`, `agent:communication:telegram:tasks`)로 응답을 분기합니다.
  * **태스크 디스패치 및 의존성 주입**: 하위 에이전트의 Redis 큐로 작업을 분배하며, 복합 작업 시 앞 단계의 결과를 `{{step_N.result.field}}` 플레이스홀더로 뒷 단계에 주입합니다.
  * **중앙 상태 관리 (Hybrid Storage)**: 사용자 세션, 대화 이력(SQLite WAL 모드) 및 현재 큐 상태(Redis)를 전역으로 추적 관리합니다.
  * **생명주기 및 헬스 모니터링**: `HealthMonitor`를 통해 연결된 하위 에이전트의 하트비트 체크 및 서킷 브레이커(Circuit Breaker) 동작 제어. NLU 라우팅 시 Redis에서 동적으로 등록된 에이전트 캐퍼빌리티를 로드합니다.
  * **사용자 승인(Human-in-the-loop)**: 파괴적인 작업 전 `communication_agent`(플랫폼별)를 통해 승인을 요청하고 `orchestra:approval:{approval_id}` 키로 결과를 대기합니다. 승인 타임아웃은 300초입니다.
  * **마켓플레이스 에이전트 설치**: `MarketplaceHandler`가 외부 URL에서 에이전트 매니페스트를 가져와 `AgentBuilderHandler`로 빌드, `AgentRegistry`(인메모리)와 `HealthMonitor`(Redis)에 런타임 중 동적 등록합니다.
* **동작 방식**: 
  FastAPI가 `POST /tasks`로 요청을 받아 Redis `agent:orchestra:tasks`에 넣으면, `OrchestraManager` 루프가 이를 꺼내어 NLU로 분석한 뒤 해당 하위 에이전트의 큐로 `DispatchMessage`를 발행(Pub)합니다. 이후 해당 태스크의 응답을 `blpop`으로 대기합니다. 각 태스크는 비동기(`asyncio.create_task`)로 병렬 처리됩니다.
* **시퀀스**:
  User → POST `/tasks` → Orchestra Manager → NLU → 하위 에이전트 큐 → 하위 에이전트 → POST `/results` → Orchestra Manager → Comm Agent (플랫폼별 큐) → User
* **NLU 엔진**:
  * `NLUEngine` 클래스가 `LLMProviderProtocol`을 추상화하여 Gemini, Claude, Local 모두 동일하게 작동합니다.
  * `LLM_BACKEND` 환경변수로 공급자 선택 (기본값: `gemini`). 레거시 `NLU_BACKEND` 환경변수도 폴백으로 지원합니다.
  * `GeminiNLUEngine`, `ClaudeNLUEngine`은 하위 호환성을 위한 별칭 클래스로 유지됩니다.
  * 최대 3회 재시도, 신뢰도(`confidence_score`) 임계값 미달 시 자동으로 `clarification` 전환.
* **예외 처리**:
  * 하위 에이전트 무응답 시 Timeout 처리 및 사용자에게 오류 회신.
  * 과부하(Rate Limit/Failures) 발생 에이전트에 대한 디스패치 차단(Circuit Open).
  * 멀티스텝 플랜 중 특정 단계 `FAILED` 시 즉시 중단 후 오류 회신 (롤백 미구현).
* **연계 에이전트**: 모든 하위 에이전트 및 Communication Agent (Slack/Discord/Telegram).
* **한계**: 오케스트라가 단일 병목점(Bottleneck)이 될 수 있으며, 복잡한 Plan의 경우 중간에 실패 시 롤백(Compensation) 로직이 미구현 상태입니다.

---

## 2. Archive Agent (아카이브 에이전트)
* **해당 코드**: `agents/archive_agent/` (`unified_agent.py`, `notion/agent.py`, `notion/notion_parser.py`, `notion/task_analyzer.py`, `obsidian/agent.py`, `obsidian/obsidian_agent.py`, `redis_listener.py`, `fastapi_app.py`, `main.py`, `models.py`, `protocols.py`)
* **목적**: 지식 베이스의 영구 저장, 조회, 삭제를 담당하는 시스템의 "장기 기억 장치" 역할.
* **기능**:
  * **Notion 지원**: 데이터베이스 목록 조회(`list_databases`), 스키마 쿼리(`get_database_schema`), 데이터베이스 아이템 조회(`query_database`), 페이지 상세 읽기(`get_page`), 페이지 생성(`create_page`), 전체 검색(`search`).
  * **Obsidian 지원**: 로컬 마크다운 파일 기반 볼트(Vault)의 읽기(`read_file`), 쓰기, 덧붙이기, 파일 삭제 및 검색.
  * **지능형 자율 복구(Self-Healing)**: ID가 틀리거나 제목만 주어진 경우 자체적으로 검색을 수행하여 대상을 찾고 작업을 진행합니다.
  * **데이터 하이브리드 캐싱**: `shared_core.storage.SqliteStorageManager`를 이용해 방대한 JSON 및 텍스트를 내부 DB(`archive_cache.db`)에 분산 저장하고 오케스트라에는 참조 ID(`reference_id`)만 반환.
  * **태스크 분석**: `notion/task_analyzer.py`를 통한 노션 기반 태스크 기획안 생성 지원 (레거시 `analyze_task` 액션).
* **동작 방식**: 
  `redis_listener`가 작업을 수신하면 `UnifiedArchiveAgent`가 명령의 컨텍스트(경로, 텍스트 내 특정 키워드)를 판단해 `NotionAgent` 또는 `ObsidianAgent`로 라우팅합니다.
* **시퀀스**:
  Orchestra → Redis 큐 → Listener → Unified Agent → (Notion API | File I/O) → Local DB Save → POST `/results` (Orchestra)
* **예외 처리**:
  * 파일이나 페이지가 없는 경우 검색 fallback 실행, 그래도 없으면 명시적 오류(ValueError/FileNotFoundError) 반환.
  * API 호출 실패 시 HTTP 통신 예외 캐치.
* **연계 에이전트**: `orchestra_agent`.
* **한계**: 외부 노션 API의 Rate Limit에 구속되며, 동기화되지 않은 오프라인 옵시디언 볼트 접근 시 충돌 가능성.

---

## 3. Communication Agent (소통 에이전트)
* **해당 코드**: `agents/communication_agent/` (`main.py`, `listener_main.py`, `models.py`, `protocols.py`, `slack/agent.py`, `slack/dispatcher.py`, `slack/fastapi_app.py`, `slack/formatter.py`, `slack/listener.py`, `slack/llm_classifier.py`, `slack/message_cleaner.py`, `slack/notion_parser.py`, `slack/redis_broker.py`, `discord/agent.py`, `discord/fastapi_app.py`, `discord/formatter.py`, `telegram/agent.py`, `telegram/fastapi_app.py`, `telegram/formatter.py`)
* **목적**: 외부 채널(Slack, Discord, Telegram)과 내부 AI 에이전트 간의 입출력 게이트웨이.
* **기능**:
  * **Slack**: SocketMode 리스너로 메시지 수신, 오케스트라 응답/진행률/승인 요청 버튼(Interactive Message)을 사용자 채널에 렌더링.
  * **Discord**: `discord.py` 라이브러리 기반. `discord.ui.Button`/`discord.ui.View`를 이용한 승인 버튼(승인/수정 요청/취소). 진행 상태 메시지 편집(edit) 지원.
  * **Telegram**: `python-telegram-bot` 라이브러리 기반. 인라인 키보드(`InlineKeyboardMarkup`)로 승인 버튼 구현. `CallbackQuery` 핸들러로 버튼 클릭 처리. HTML 파싱 모드 사용.
  * **플랫폼별 독립 Redis 큐**: Slack(`agent:communication:tasks`), Discord(`agent:communication:discord:tasks`), Telegram(`agent:communication:telegram:tasks`)으로 분리 운영.
  * **공유 RedisBroker**: `slack/redis_broker.py`에서 모든 플랫폼의 큐 키 상수와 공통 브로커 로직을 관리합니다.
  * **하트비트**: 각 플랫폼 에이전트가 15초 주기로 Redis에 헬스 상태를 업데이트합니다.
* **동작 방식**: 
  각 플랫폼의 이벤트 리스너가 백그라운드에서 구동되며, 동시에 플랫폼별 Redis 큐를 비동기로 리스닝하여 출력 메시지를 해당 플랫폼 API에 전송합니다.
* **시퀀스**:
  [Inbound] Platform User → Event Listener → Comm Agent → Orchestra POST `/tasks` (source 태그 포함)
  [Outbound] Orchestra → 플랫폼별 Redis 큐 → Comm Agent → Platform API (ChatPostMessage / discord.send / bot.send_message)
* **예외 처리**:
  * Discord: HTTP 429(Rate Limit) 시 `Retry-After` 헤더 값만큼 대기 후 재시도.
  * Telegram: `RetryAfter` 예외 캐치 후 `retry_after` 초 대기 후 재시도.
  * Slack: 재시도 로직 내장.
  * 모든 플랫폼: 승인 버튼 5분 타임아웃 후 자동 비활성화.
* **연계 에이전트**: `orchestra_agent`.
* **한계**: 각 플랫폼마다 전용 봇 토큰/앱 설정 필요. 신규 채널 추가 시 에이전트 클래스, FastAPI 앱, 포매터, Redis 큐 키를 각각 구현해야 합니다.

---

## 4. Research Agent (리서치 에이전트)
* **해당 코드**: `agents/research_agent/` (`agent.py`, `providers.py`, `config.py`, `interfaces.py`, `main.py`)
* **목적**: 웹 검색 및 외부 지식을 조사하여 보고서나 원문을 수집.
* **기능**:
  * 외부 Search Provider (DuckDuckGo, Google 등) 연동 질의 분석.
  * 검색된 방대한 데이터(원문 및 분석 결과)를 로컬 분산 저장소(`research_cache.db`)에 캐싱하여 중앙 DB의 비대화(Bloat) 방지.
* **동작 방식**: 
  디스패치 액션(`investigate`) 수신 시 프로바이더를 통해 외부 API를 호출. 반환된 대용량 텍스트를 로컬 SQLite에 적재하고 식별자와 요약문만 오케스트라로 던집니다.
* **시퀀스**:
  Orchestra → Redis 큐 → Research Agent → External Search API → SqliteStorageManager Save → POST `/results`
* **예외 처리**:
  * 검색 API 할당량 초과, 타임아웃, 결과 없음 등의 예외를 `FAILED` 상태로 캡처하여 오케스트라에 보고.
* **연계 에이전트**: `orchestra_agent` (종종 `archive_agent`로 이어지는 멀티스텝 작업의 선행 단계로 활약).
* **한계**: 검색 엔진 API 비용 및 크롤링 차단(CAPTCHA)에 따른 데이터 수집 한계.

---

## 5. File Agent (파일 에이전트)
* **해당 코드**: `agents/file_agent/` (`agent.py`, `validator.py`, `config.py`, `interfaces.py`, `main.py`)
* **목적**: 로컬 서버의 파일 시스템에 대한 안전한 입출력 전담.
* **기능**:
  * 텍스트 파일 읽기(`read_file`), 쓰기(`write_file`), 파일 검색(`search_files`), 덮어쓰기, 수정(Append), 삭제.
  * **보안성(Security)**: `PathValidator`를 통해 지정된 `allowed_roots` 바깥으로 나가는 Path Traversal 공격 차단.
  * **안정성**: 최대 파일 크기 제한(MB 단위)을 통해 메모리 폭주 방지.
* **동작 방식**: 
  요청받은 `file_path`를 Validator로 검증한 뒤 `pathlib`을 사용하여 직접 I/O를 수행합니다.
* **시퀀스**:
  Orchestra → Redis 큐 → File Agent → Path Validation → OS File I/O → POST `/results`
* **예외 처리**:
  * 존재하지 않는 파일 접근 시 명확한 메시지 반환.
  * 크기 초과, 쓰기 권한 없음, 보안 위배 경로 등에서 예외 처리 및 에러 코드(EXECUTION_ERROR) 반환.
* **연계 에이전트**: `orchestra_agent` (보통 `coding_agent`나 `sandbox_agent`와 연계됨).
* **한계**: 에이전트가 실행되는 물리적/가상적 머신 내의 스토리지로만 국한됩니다.

---

## 6. Sandbox Agent (샌드박스 에이전트)
* **해당 코드**: `agents/sandbox_agent/` (`agent.py`, `pool.py`, `firecracker.py`, `docker_sandbox.py`, `network.py`, `vsock.py`, `models.py`, `protocols.py`, `redis_listener.py`, `fastapi_app.py`, `main.py`, `guest/guest_agent.py`)
* **목적**: 시스템 프롬프트나 LLM이 생성한 임의의 코드(주로 Python)를 메인 호스트와 완벽히 격리된 환경에서 안전하게 실행.
* **기능**:
  * `KVM` 가용 여부에 따라 **Firecracker MicroVM** 또는 **Docker 컨테이너**를 동적 프로비저닝 (VMPool 관리).
  * 코드 실행 시간 제한(Timeout), 메모리 제한 등 하드웨어 격리.
  * 표준 입출력 캡처 및 Exit Code 반환.
  * **TAP 네트워크 격리** (`network.py`): 각 Firecracker VM에 전용 TAP 디바이스를 할당합니다. VM → 호스트 트래픽만 허용하고 인터넷은 `iptables DROP`으로 완전 차단. `172.16.0.0/16` 서브넷에서 VM별 `/30` 슬라이스를 동적 할당합니다.
  * **VSock 통신** (`vsock.py`): Firecracker VM과 호스트 간 통신에 `virtio-vsock`(UDS 프록시)을 사용합니다. `[uint32 BE 길이][JSON payload]` 형식의 길이 프리픽스 프레이밍으로 fragmentation을 방지합니다. Guest Agent 리스닝 포트는 `52000`입니다.
  * **Guest Agent** (`guest/guest_agent.py`): VM 내부에서 실행되며 호스트로부터 코드를 수신하고 실행 결과를 VSock으로 반환합니다.
* **동작 방식**: 
  작업 지시가 오면 `VMPool`에서 미리 워밍업된 또는 빈 인스턴스를 `acquire`한 후, VSock을 통해 Guest Agent에 코드를 투입하여 실행. 완료 후 자원을 `release` (또는 파괴)합니다.
* **시퀀스**:
  Orchestra → Redis 큐 → Sandbox Agent → VMPool Acquire → TAP/VSock 설정 → 코드 주입 및 실행 (Guest Agent) → VMPool Release → POST `/results`
* **예외 처리**:
  * 무한 루프 코드 작성 시 Timeout Kill 적용.
  * OOM(Out of Memory) 발생 시 강제 종료 후 에러 코드 반환.
  * VSock 헤더/페이로드 수신 타임아웃(헤더: 5초, 페이로드: 30초) 및 JSON 파싱 오류 처리.
* **연계 에이전트**: 주로 `orchestra_agent` 및 코드를 생성하는 에이전트.
* **한계**: Firecracker 가동을 위해 호스트 인프라에 KVM 지원(Nested Virtualization 등)이 필수적이며, TAP/iptables 설정을 위해 Linux 환경 및 루트(또는 CAP_NET_ADMIN) 권한이 필요합니다.

---

## 7. Schedule Agent (스케줄 에이전트)
* **해당 코드**: `agents/schedule_agent/` (`agent.py`, `providers.py`, `config.py`, `interfaces.py`, `main.py`)
* **목적**: 사용자의 일정을 캘린더에 연동하여 시간 관리 자동화 제공.
* **기능**:
  * Google Calendar API 등 연동 (이벤트 생성, 삭제, 리스트 조회, 수정).
  * 지원 액션: `list_schedules`, `add_schedule`, `modify_schedule`, `remove_schedule`.
* **동작 방식**: 
  `list_schedules`, `add_schedule` 등의 액션과 함께 날짜/시간 포맷의 파라미터를 받아 프로바이더를 통해 외부 API와 동기화.
* **시퀀스**:
  Orchestra → Redis 큐 → Schedule Agent → Calendar Provider (Google API) → POST `/results`
* **예외 처리**:
  * 인증 토큰 에러, API 통신 에러, 잘못된 DateTime 포맷 입력 예외 처리.
* **연계 에이전트**: `orchestra_agent`.
* **한계**: 플랫폼 종속성(Google Calendar). 시간대(Timezone) 처리에 유의하지 않으면 오류 가능성이 높습니다.

---

## 8. Shared Core (공유 코어)
* **해당 코드**: `shared_core/` (`agent_logger.py`, `llm/`, `messaging/`, `storage/`, `sandbox/`, `calendar/`, `search/`)
* **목적**: 모든 에이전트가 공통으로 사용하는 핵심 인프라 모듈 모음.
* **주요 모듈**:
  * **`llm/`**: LLM 공급자 추상화. `LLMProviderProtocol` 인터페이스를 기반으로 `build_llm_provider()` 팩토리가 `LLM_BACKEND` 환경변수에 따라 Gemini, Claude, Local 공급자를 반환합니다.
  * **`messaging/`**: Redis Pub/Sub 브로커(`broker.py`)와 에이전트 간 통신 스키마(`schema.py`) 정의.
  * **`storage/`**: `SqliteStorageManager`를 통한 대용량 데이터 분산 저장. 에이전트별 로컬 SQLite DB에 적재하고 참조 ID만 반환하는 하이브리드 캐싱 패턴을 제공합니다.
  * **`sandbox/`**: 샌드박스 클라이언트(`client.py`), 모델(`models.py`), 믹스인(`mixin.py`) — 에이전트에서 샌드박스를 사용하기 위한 공통 인터페이스.
  * **`calendar/`**: 캘린더 공급자 인터페이스(`interfaces.py`).
  * **`search/`**: 검색 공급자 인터페이스(`interfaces.py`).
