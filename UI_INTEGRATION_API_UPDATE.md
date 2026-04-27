# 오케스트라 에이전트 API 업데이트 명세서 (UI 연동용)

이 문서는 최근 TDD 방식으로 추가 및 개선된 API 엔드포인트들의 명세서입니다. 
별도로 진행 중인 **UI 프로젝트(프론트엔드/클라이언트)**에서 즉시 연동하여 사용할 수 있도록 작성되었습니다.

> **⚠️ [중요] 공통 보안 및 유효성 검사 (Client-Side Validation 필수)**
> 백엔드에 DoS 방어 및 보안 정책이 추가되었습니다. UI 폼(Form)에서 다음 제약 조건을 반드시 검증해 주세요.
> *   **사용자 입력 (Task Content):** 최대 10,000자 제한
> *   **LLM API 키 (API Key):** 최대 300자 제한
> *   **각종 ID (`user_id`, `session_id`, `task_id` 등):** 최대 100자 제한

---

## 1. 🔐 사용자별 LLM API 키 업데이트 (보안 강화)

사용자가 자신의 개별 LLM 제공업체(Gemini, Claude, OpenAI 등) API 키를 안전하게 등록하고 업데이트할 수 있습니다. 등록된 키는 백엔드 DB에 **대칭키 암호화(AES)** 처리되어 안전하게 보관됩니다.

*   **URL:** `PUT /users/{user_id}/llm_keys/{provider_name}`
*   **Path Parameters:**
    *   `user_id` (string, max 100): 대상 사용자의 고유 ID (예: `user_123`)
    *   `provider_name` (string): API 키를 등록할 LLM 제공업체 이름 (예: `gemini`, `claude`, `openai`, `local`)
*   **Headers:**
    *   `X-API-Key`: 클라이언트 인증 키 (필수)
*   **Request Body (JSON):**
    ```json
    {
      "api_key": "사용자가 발급받은 실제 API 키 문자열 (최대 300자)"
    }
    ```
*   **Response (200 OK):**
    ```json
    {
      "message": "LLM API key updated successfully."
    }
    ```
*   **에러 응답:**
    *   `400 Bad Request`: 지원하지 않는 `provider_name`이거나 `api_key`가 누락/빈 값일 경우.
    *   `404 Not Found`: 해당 `user_id`의 사용자 프로필을 찾을 수 없을 경우.
    *   `422 Unprocessable Entity`: `api_key` 길이가 300자를 초과하는 경우.

*(참고: `GET /users/{user_id}/profile` 호출 시 보안을 위해 `llm_keys` 정보는 응답에서 자동으로 제외됩니다.)*

---

## 2. 🚀 태스크 제출 (Rate Limiting 및 Idempotency 추가)

기존 태스크 제출 API에 어뷰징 방지 및 중복 실행 방지 기능이 추가되었습니다.

*   **URL:** `POST /tasks`
*   **Headers:**
    *   `X-API-Key`: 클라이언트 인증 키 (필수)
    *   `X-Idempotency-Key`: (선택) 중복 요청 방지를 위한 고유 키 (UUID 등). 네트워크 오류로 재시도 시 동일한 키를 보내면 중복 실행을 막고 캐시된 결과를 반환합니다.
*   **Request Body (JSON):**
    ```json
    {
      "content": "오늘 날씨 어때? (최대 10,000자)",
      "user_id": "api-user (최대 100자)",
      "channel_id": "api (최대 100자)",
      "session_id": "optional-session-123 (최대 100자)",
      "callback_url": "https://... (최대 1,000자)"
    }
    ```
*   **에러 응답:**
    *   `422 Unprocessable Entity`: `content`가 10,000자를 초과하거나 기타 길이 제한을 위반한 경우.
    *   `429 Too Many Requests`: 짧은 시간에 너무 많은 요청을 보낸 경우 (Rate Limiting). `Retry-After` 헤더를 확인하여 재시도 시간을 UI에 안내해 주세요.

---

## 3. 🛑 태스크 강제 취소 (UX 제어)

진행 중인 태스크(작업)가 너무 오래 걸리거나 잘못된 요청일 경우, 사용자가 강제로 작업을 취소할 수 있습니다.

*   **URL:** `POST /tasks/{task_id}/cancel`
*   **Path Parameters:**
    *   `task_id` (string, max 100): 취소할 대상 태스크의 고유 ID
*   **Headers:**
    *   `X-API-Key`: 클라이언트 인증 키 (필수)
*   **Response (200 OK):**
    ```json
    {
      "status": "CANCELLED",
      "task_id": "fe0fc0de-9179-4576-8c00-b96149276e1b"
    }
    ```
*   **에러 응답:**
    *   `400 Bad Request`: 태스크가 이미 완료(COMPLETED)되었거나 실패(FAILED)한 경우, 혹은 이미 취소(CANCELLED)된 경우.

**UI 적용 방안:** 사용자가 메시지를 보낸 후 로딩 중일 때 [작업 취소] 버튼을 노출시키고, 버튼 클릭 시 이 API를 호출하세요.

---

## 4. ⏳ 진행 상태 실시간 피드백 폴링 (UX 피드백)

기존 태스크 상태 조회 API에 `include_logs=true` 쿼리 파라미터를 추가하여, 태스크의 **최근 진행 로그(Progress events)**를 함께 받아볼 수 있습니다.

*   **URL:** `GET /tasks/{task_id}?include_logs=true`
*   **Path Parameters:**
    *   `task_id` (string, max 100): 조회할 대상 태스크의 고유 ID
*   **Query Parameters:**
    *   `include_logs` (boolean): `true`로 설정 시 최근 로그 최대 5개를 `recent_logs` 배열로 포함하여 반환합니다.
*   **Headers:**
    *   `X-API-Key`: 클라이언트 인증 키 (필수)
*   **Response (200 OK):**
    ```json
    {
      "task_id": "fe0fc0de-...",
      "status": "PROCESSING",
      "session_id": "...",
      "recent_logs": [
        {
          "id": 42,
          "agent_name": "research_agent",
          "action": "searching",
          "message": "구글에서 '최신 AI 트렌드'를 검색하고 있습니다...",
          "timestamp": "2026-04-26T05:12:30.123Z"
        },
        {
          "id": 41,
          "agent_name": "orchestra",
          "action": "dispatch",
          "message": "리서치 에이전트에게 작업을 할당했습니다.",
          "timestamp": "2026-04-26T05:12:28.000Z"
        }
      ]
    }
    ```

**UI 적용 방안:** 태스크 완료를 기다리는 동안 이 API를 주기적(예: 1~2초 간격)으로 폴링하고, `recent_logs[0].message` 값을 추출하여 로딩 스피너 하단에 "현재 상태: 구글에서 검색 중..." 처럼 실시간 텍스트로 보여주세요. (참고: 백엔드에서 로그 내 민감한 API 키 패턴은 자동으로 `***MASKED***` 처리되어 안전하게 전달됩니다.)

---

## 5. 💡 동적 추천 프롬프트 (UX 온보딩)

초기 화면(빈 채팅창)에서 사용자가 어떤 질문을 해야 할지 막막할 때, **현재 시스템에서 가용한 에이전트들의 기능**을 파악하여 알맞은 추천 질문 목록을 동적으로 반환합니다.

*   **URL:** `GET /prompts/suggestions`
*   **Headers:**
    *   `X-API-Key`: 클라이언트 인증 키 (선택/시스템 설정에 따라 다름)
*   **Response (200 OK):**
    ```json
    {
      "suggestions": [
        "오늘 날씨 어때?",
        "간단한 인사말 작성해줘",
        "간단한 파이썬 스크립트 작성해줘",
        "내일 오후 3시에 회의 일정 추가해줘",
        "최신 AI 트렌드 요약해줘"
      ]
    }
    ```
    *(참고: 반환되는 `suggestions` 배열의 텍스트는 헬스 체크를 통과하여 현재 "살아있는" 에이전트의 종류에 따라 동적으로 변경되며, 최대 5개로 제한됩니다.)*

**UI 적용 방안:** 새로운 채팅 세션을 시작할 때 이 API를 한 번 호출하고, 반환된 문자열 리스트를 채팅 입력창 상단에 둥근 버튼(Chips/Tags) 형태로 나열해 주세요. 사용자가 버튼을 클릭하면 해당 텍스트가 즉시 입력되도록 처리하면 됩니다.

---

## 6. 🛠️ 관리자용 샌드박스 API 키 관리 (동적 보안)

관리자 전용 대시보드에서 코드 실행 샌드박스(`sandbox_agent`)에 접근하기 위한 API 키를 실시간으로 생성, 조회, 삭제할 수 있습니다.

*   **기본 URL:** `/admin/sandbox/keys`
*   **Headers:**
    *   `X-Admin-API-Key`: 관리자 인증 키 (필수)

### 6.1. 새로운 API 키 생성
*   **URL:** `POST /admin/sandbox/keys`
*   **Request Body (JSON):**
    ```json
    {
      "label": "키 식별용 이름 (예: prod-deployment)"
    }
    ```
*   **Response (201 Created):**
    ```json
    {
      "status": "created",
      "label": "prod-deployment",
      "key": "4a7b...f92e (실제 64자 랜덤 헥사 키)",
      "note": "이 키는 다시 조회할 수 없으므로 안전한 곳에 저장하세요."
    }
    ```

### 6.2. 등록된 API 키 목록 조회
*   **URL:** `GET /admin/sandbox/keys`
*   **Response (200 OK):**
    ```json
    {
      "total": 2,
      "keys": {
        "4a7b9cde...f92e": "prod-deployment",
        "1234abcd...7890": "dev-local"
      },
      "raw_keys_count": 2
    }
    ```
    *(보안을 위해 키 값은 마스킹 처리되어 `앞 8자리...뒤 4자리` 형식으로만 제공됩니다.)*

### 6.3. API 키 삭제
*   **URL:** `DELETE /admin/sandbox/keys/{key_prefix}`
*   **Path Parameters:**
    *   `key_prefix` (string): 삭제할 키의 앞부분 8자리 (조회 API에서 확인된 prefix)
*   **Response (200 OK):**
    ```json
    {
      "status": "deleted",
      "deleted_prefix": "4a7b9cde"
    }
    ```

**UI 적용 방안:** 관리자 대시보드의 '보안 설정' 탭에서 현재 활성화된 샌드박스 키 목록을 테이블 형태로 보여주고, [새 키 생성] 버튼을 통해 키를 발급받을 수 있게 구성하세요. 키 생성 직후에만 전체 키 값을 보여주는 모달(Modal) 창을 띄워 사용자가 복사할 수 있도록 유도해야 합니다.