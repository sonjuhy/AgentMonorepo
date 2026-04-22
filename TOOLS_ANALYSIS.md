# Agent Builder 도구 분석 보고서

본 문서는 `AgentMonorepo`의 `tools/agent_builder` 내에 있는 에이전트 생성 자동화 유틸리티(Agent Builder)의 목적, 기능, 시퀀스, 동작 방식, 예외 처리 및 한계점을 상세하게 분석한 보고서입니다.

> **최종 갱신**: 2026-04-22 기준 실제 코드 분석 반영

---

## 1. 개요 및 목적 (Purpose)

Agent Builder는 개발자가 비즈니스 로직(user_code)과 필요한 패키지 목록만 제공하면, 시스템에 즉시 통합 가능한 **마이크로서비스 기반의 에이전트 보일러플레이트(Boilerplate) 코드를 자동으로 생성**해주는 개발 및 관리 도구입니다.

*   **생산성 극대화**: Redis Pub/Sub 리스너, FastAPI 헬스 체크, Pydantic 모델, Dockerfile 설정 등 반복적인 인프라 코드 작성을 자동화합니다.
*   **표준화**: 모든 에이전트가 동일한 구조(통신 프로토콜, 로깅, 예외 처리 등)를 갖도록 강제하여 모노리포의 유지보수성을 높입니다.
*   **다국어 지원**: Python뿐만 아니라 JavaScript(Node.js) 기반의 에이전트도 일관된 파이썬 래퍼(Wrapper)와 함께 생성할 수 있습니다.
*   **보안 내재화**: 컨테이너의 권한(네트워크, 파일시스템, 메모리, CPU, PID 등)을 미리 정의된 프리셋(minimal, standard, trusted)으로 엄격하게 제어합니다.

---

## 2. 구성 요소 및 기능 (Components & Features)

Agent Builder는 여러 모듈로 분리되어 각자의 역할을 수행합니다.

### 2.1. `builder.py` (핵심 빌드 엔진)
*   **기능**: 사용자로부터 에이전트 이름, 언어(`python` | `javascript`), 코드, 패키지 목록, 포트, 권한(Permissions)을 입력받아 `agents/{name}_agent` 디렉터리를 생성합니다.
*   **생성 파일 목록**:
    *   **Python 공통**: `__init__.py`, `models.py`, `protocols.py`, `redis_listener.py`, `fastapi_app.py`, `main.py`
    *   **Python 전용 추가**: `user_code.py`, `agent.py`, `requirements.txt`, `Dockerfile`
    *   **JavaScript 전용 추가**: `user_code.js`, `_js_shim.js`, `js_runner.py`, `agent.py`, `requirements.txt`, `package.json`, `Dockerfile`
*   **동작 방식**: 
    *   입력된 이름 정규화 (snake_case 소문자, `_agent` 접미사 자동 제거).
    *   `validator.py`를 호출하여 코드 및 패키지 유효성 사전 검사 (`validate_code=True` 시).
    *   `templates.py`에 정의된 템플릿 문자열에 변수(`SNAKE_NAME`, `CLASS_NAME`, `PORT`, `DESCRIPTION`, 권한 스니펫 등)를 주입하여 실제 파일들을 디스크에 씁니다.
    *   `BuildResult` 데이터클래스로 결과 반환 (생성 디렉터리, 파일 목록, 검증 결과, 다음 단계 가이드 포함).
    *   빌드 완료 후 `schema.py` 등록 및 `docker-compose.yml` 서비스 추가 방법을 포함한 Next Steps 가이드를 출력합니다.

### 2.2. `permissions.py` (컨테이너 보안 모델)
*   **기능**: 생성될 에이전트의 Dockerfile 및 `docker-compose.yml`에 들어갈 보안/리소스 제한 설정을 관리하는 dataclass 모델입니다.
*   **설정 항목**:
    *   `network`: `"none"` | `"internal"` | `"full"` — 네트워크 접근 모드
    *   `filesystem`: `"readonly"` | `"readwrite"` — 파일시스템 접근 모드
    *   `writable_paths`: readonly 모드에서 tmpfs로 마운트할 경로 (기본: `["/tmp"]`)
    *   `memory_mb`, `cpu_limit`, `pids_limit` — 리소스 제한
    *   `extra_capabilities` — ALL DROP 이후 추가로 허용할 Linux Capability 목록
    *   `run_as_nonroot`, `no_new_privileges` — 프로세스 보안 컨텍스트
    *   `allow_llm_access`, `llm_env_vars` — LLM API 접근 및 환경변수 주입
*   **프리셋**:
    *   `minimal`: 네트워크 완전 차단(`none`), 읽기 전용, 256MB, CPU 0.5코어, 최대 PID 64. (코드 실행 등 격리 환경용)
    *   `standard`: 내부 네트워크(`internal`), 읽기 전용, 512MB, CPU 1.0코어. (일반적인 사내 API 통신 에이전트용, **기본값**)
    *   `trusted`: 외부 인터넷(`full`), 읽기/쓰기, 1GB, CPU 2.0코어, 최대 PID 200, LLM 접근 허용. (외부 검색, LLM 통신 등 특수 에이전트용)
*   **LLM 접근 환경변수**: `allow_llm_access=True` 시 `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_API_KEY` 5개 변수를 컨테이너에 자동 주입합니다.
*   **동작 방식**: 설정된 값에 따라 Dockerfile의 비루트 사용자 설정 구문(`RUN addgroup/adduser...`)과 docker-compose의 `security_opt`, `cap_drop`, `cap_add`, `read_only`, `tmpfs`, `mem_limit`, `cpus`, `pids_limit`, 네트워크, LLM 환경변수를 문자열로 렌더링합니다.

### 2.3. `validator.py` (유효성 검사기)
*   **기능**: 코드가 올바른 문법을 가졌는지, 패키지가 존재하는지 런타임 전에 검사하여 "생성 후 실행 실패"를 방지합니다.
*   **동작 방식**:
    *   **Python**: `ast.parse()`로 문법 검사, AST 트리를 순회하여 `run()` 함수의 존재 여부 확인. `pip install --dry-run`으로 패키지 설치 가능 여부 확인.
    *   **JavaScript**: 임시 파일을 만들어 `node --check`로 문법 검사. 정규식을 통해 `module.exports = { run }` 패턴이 있는지 검사. npm 패키지명 규칙 검사.

### 2.4. `templates.py` (코드 템플릿 저장소)
*   **기능**: 에이전트를 구성하는 모든 파일의 원본 템플릿 문자열을 보관합니다. Python 래퍼 코드(`AGENT_PY_PYTHON`, `AGENT_PY_JS`), FastAPI 앱(`FASTAPI_APP_PY`), Redis 리스너(`REDIS_LISTENER_PY`), Dockerfile(`DOCKERFILE_PYTHON`, `DOCKERFILE_JS`), JS 심(`JS_SHIM`, `JS_RUNNER_PY`) 등이 포함되어 있습니다.
*   `render()` 함수가 템플릿 문자열에 `**vars_` 딕셔너리를 `str.format_map()`으로 주입합니다.

### 2.5. `cli.py` & `__main__.py` (명령어 인터페이스)
*   **기능**: 터미널에서 명령어로 Agent Builder를 실행할 수 있게 해주는 인터페이스입니다. (예: `python -m tools.agent_builder create my_agent ...`)

---

## 3. 동작 시퀀스 (Execution Sequence)

새로운 에이전트를 생성할 때의 파이프라인 흐름입니다.

1.  **입력 수신 (Input)**: CLI(`python -m tools.agent_builder`) 또는 Python API, 또는 Orchestra의 `MarketplaceHandler`(런타임 동적 설치)를 통해 에이전트 생성 파라미터가 전달됩니다.
2.  **유효성 검사 (Validate)**: `validator.py`가 코드(Syntax/AST) 및 패키지를 검사합니다. 에러 시 빌드를 중단(또는 경고만 띄우고)합니다.
3.  **이름 정규화 (Normalize)**: `_normalize_name()`이 입력 이름을 snake_case 소문자로 변환하고 `_agent` 접미사를 제거합니다.
4.  **디렉터리/권한 설정 (Init)**: `ContainerPermissions`를 통해 해당 에이전트의 권한 수준을 확정하고 디렉터리(`agents/{name}_agent`)를 생성합니다.
5.  **파일 렌더링 및 쓰기 (Render & Write)**: `templates.py`의 문자열을 포맷팅하여 필수 보일러플레이트 파일과 사용자 코드를 디스크에 씁니다.
    *   Python: `user_code.py`, `agent.py`, `models.py`, `protocols.py`, `redis_listener.py`, `fastapi_app.py`, `main.py`, `requirements.txt`, `Dockerfile`
    *   JS: 위 공통 인프라 파일 + `user_code.js`, `_js_shim.js`, `js_runner.py`, `package.json`, `Dockerfile`
6.  **결과 반환 (Output)**: `BuildResult`를 반환하며, `schema.py` 에이전트 이름 등록, `docker-compose.yml` 서비스 스니펫 추가, Docker 이미지 빌드·실행·테스트 방법을 담은 Next Steps 가이드를 출력합니다.

---

## 4. Orchestra와의 통합 (Runtime Integration)

`AgentBuilder`는 단독 CLI 도구일 뿐만 아니라, Orchestra Agent의 `MarketplaceHandler`와 `AgentBuilderHandler`를 통해 **런타임에 동적으로 호출**됩니다.

*   `MarketplaceHandler`가 외부 URL에서 에이전트 매니페스트(JSON)를 가져옵니다.
*   매니페스트 필수 필드: `name`(에이전트 이름), `code`(실행 코드)
*   선택 필드: `language`, `description`, `packages`, `port`, `permissions`(프리셋 이름), `lifecycle_type`, `capabilities`, `nlu_description`
*   `AgentBuilderHandler.build_agent()`가 `AgentBuilder.build()`를 호출합니다.
*   빌드 완료 후 `AgentRegistry`(인메모리)와 `HealthMonitor`(Redis)에 자동 등록되어 NLU 라우팅에 즉시 활용됩니다.

---

## 5. 예외 처리 (Exception Handling)

*   **이름 유효성**: 비어있거나 영문자로 시작하지 않는 이름 요청 시 `ValueError` 발생.
*   **디렉터리 충돌**: 이미 동일한 이름의 에이전트 디렉터리가 존재할 경우 `FileExistsError` 발생 (단, `force=True` 옵션으로 덮어쓰기 가능).
*   **언어 미지원**: `"python"` 또는 `"javascript"` 외의 언어 지정 시 `ValueError` 발생.
*   **검증 타임아웃**: `pip --dry-run`이나 `node --check` 등 외부 서브프로세스 호출 시 응답이 지연되면(timeout) 에러 대신 경고(warn)만 남기고 프로세스 생성을 속행하여 시스템 멈춤을 방지합니다.
*   **권한 논리 오류**: `allow_llm_access=True`이면서 `network="none"`으로 설정된 모순된 권한 프리셋 요청 시 `ValueError` 발생.
*   **마켓플레이스 설치 오류**: `MarketplaceHandler`가 manifest 누락 필드(`name`, `code`) 또는 빌드 실패 시 `FAILED` 상태를 오케스트라에 반환합니다.

---

## 6. 연계 모듈 및 에이전트 (Linked Components)

*   **Orchestra Agent** (`agent_builder_handler.py`, `marketplace_handler.py`): 오케스트라 에이전트는 외부 마켓플레이스에서 매니페스트를 다운로드받은 뒤, 내부적으로 `AgentBuilder` API를 직접 호출하여 런타임 중에 동적으로 새로운 에이전트를 시스템에 추가(Install)하고 `AgentRegistry` + `HealthMonitor`에 등록합니다.
*   **Shared Core**: 빌드된 에이전트 코드는 `shared_core.messaging` 모듈에 의존하여 통신하며, `trusted` 권한 에이전트는 `shared_core.llm` 팩토리를 통해 LLM에 접근합니다.

---

## 7. 한계 및 고려사항 (Limitations)

*   **반자동 시스템 통합**: 파일 생성은 100% 자동화되지만, 최종적으로 통신 규격을 맞추기 위해 개발자가 수동으로 `schema.py`에 Agent Name 타입을 추가하고 `docker-compose.yml`에 스니펫을 붙여넣어야 하는 **반자동(Semi-auto)** 절차가 남아있습니다. (런타임 마켓플레이스 설치 시에는 `AgentRegistry`·`HealthMonitor` 등록만 자동화되며, `docker-compose.yml` 반영은 여전히 수동입니다.)
*   **패키지 관리의 한계**: JS 패키지(`npm`)의 경우 속도 문제로 `dry-run` 설치 테스트를 하지 않고 정규식으로 이름 형태만 검증합니다. 따라서 오타가 있는 패키지가 입력되면 나중에 Docker Image를 빌드할 때 에러가 발생합니다.
*   **Node.js 의존성**: JS 에이전트를 생성하는 환경(호스트)에 `node`가 설치되어 있지 않으면 문법 사전 검증을 수행하지 못하고 스킵(경고)하게 됩니다.
*   **동적 설치의 Docker 갱신 미지원**: 마켓플레이스를 통한 런타임 설치는 코드 파일 생성 및 레지스트리 등록까지만 자동화됩니다. 실제 컨테이너 이미지 빌드 및 `docker-compose up`은 별도 CI/CD 또는 수동 개입이 필요합니다.
