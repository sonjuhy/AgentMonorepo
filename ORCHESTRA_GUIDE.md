# 🎭 Orchestra Agent: 중앙 관제 및 보안 실행 플랫폼 가이드

## 1. 개요 (Overview)
**Orchestra Agent**는 멀티 에이전트 시스템의 중앙 지휘자 역할을 수행하는 핵심 허브입니다. 사용자의 자연어 입력을 분석(NLU)하여 적절한 하위 에이전트에게 작업을 분배하고, 전체적인 작업 상태와 보안 실행 환경(Sandbox)을 관리합니다.

최근 업데이트를 통해 비즈니스 로직과 보안 실행 계층이 완전히 분리되었으며, 엔드투엔드(End-to-End) 보안 체계를 갖춘 **Enterprise-ready** 아키텍처로 진화했습니다.

## 2. 목적 (Purpose)
*   **지능적 태스크 라우팅**: LLM을 사용하여 사용자 의도를 파악하고 최적의 에이전트 조합을 구성합니다.
*   **보안 격리 실행**: 임의의 코드를 호스트 시스템과 분리된 하드웨어 가상화 또는 커널 격리 환경에서 실행합니다.
*   **상태 및 이력 관리**: 모든 에이전트의 활동 로그와 세션 상태를 중앙에서 영구 저장 및 관리합니다.
*   **에이전트 거버넌스**: 에이전트의 등록, 헬스 체크, 권한 제어(ACL)를 통합 수행합니다.

## 3. 주요 아키텍처 (Architecture)
*   **Orchestra Hub**: 비즈니스 로직 및 NLU 엔진 (Non-root 실행).
*   **Sandbox Agent**: 코드 실행 전용 서버 (3단계 보안 격리 적용).
*   **Redis Broker**: 에이전트 간 통신 메시지 큐 (ACL 보안 격리 적용).
*   **Shared Core**: 보안 로깅 및 공통 유틸리티 레이어.

---

## 4. 설치 방법 (Installation)

### 4.1. 요구 사항
*   Docker & Docker Compose (v2.20.0 이상 권장)
*   (선택) 하드웨어 가상화 격리 사용 시: 리눅스 KVM 지원 서버
*   (선택) 커널 격리 사용 시: `runsc` (gVisor) 설치된 서버

### 4.2. 환경 설정
프로젝트 루트의 `.env.example` 파일을 복사하여 `.env`를 생성하고 필수 값을 입력합니다.

```bash
cp .env.example .env
```

**필수 설정 항목:**
*   `ADMIN_API_KEY`: 관리자 전용 API 접근 키
*   `CLIENT_API_KEY`: 일반 클라이언트 접근 키
*   `SANDBOX_API_KEY`: 에이전트 간 보안 통신용 비밀키
*   `REDIS_ORCHESTRA_PASSWORD`: Redis 관리자 비밀번호
*   `GEMINI_API_KEY`: 자연어 분석용 LLM 키

---

## 5. 실행 방법 (Execution)

### 5.1. 표준 실행 (Production 모드)
오케스트라와 샌드박스를 포함한 모든 보안 환경을 가동합니다.

```bash
# 샌드박스 프로필을 포함하여 모든 서비스 시작
docker-compose --profile sandbox up -d
```

### 5.2. 개발 모드 (샌드박스 제외)
코드 실행 기능 없이 NLU 및 기본 에이전트만 테스트할 때 사용합니다.

```bash
docker-compose up -d
```

---

## 6. 사용 방법 (Usage)

### 6.1. 사용자 태스크 요청
사용자의 자연어를 시스템에 입력합니다.
*   **Endpoint**: `POST /tasks`
*   **Header**: `X-Client-API-Key: {YOUR_KEY}`
*   **Body**: `{"content": "오늘 날씨 분석하는 파이썬 코드 실행해줘"}`

### 6.2. 샌드박스 보안 키 관리 (Admin)
실시간으로 샌드박스 접근 권한을 제어합니다. (자세한 내용은 `UI_INTEGRATION_API_UPDATE.md` 참조)
*   **조회**: `GET /admin/sandbox/keys`
*   **생성**: `POST /admin/sandbox/keys`

### 6.3. 상태 모니터링
시스템 전체 헬스 및 에이전트 가동 현황을 조회합니다.
*   **Endpoint**: `GET /health`

---

## 7. 핵심 보안 기능 (Security Features)

| 보안 기능 | 설명 |
| :--- | :--- |
| **3-Tier Sandbox** | Firecracker(물리 격리), gVisor(커널 격리), Docker(컨테이너) 순으로 최상의 보안 기술 자동 선택 |
| **Redis ACL** | 에이전트별 전용 계정 부여로 타 에이전트 큐 침범 원천 차단 |
| **Socket-less Hub** | 메인 허브에서 Docker 소켓 마운트를 제거하여 호스트 루트 권한 탈취 방지 |
| **Log Masking** | 로그 출력 시 API 키 및 민감 토큰 자동 감지 및 `***MASKED***` 처리 |
| **Non-root Execution** | 모든 에이전트 프로세스를 비관리자(`appuser`) 권한으로 실행 |

---

## 8. 지원 에이전트 목록
*   **Archive Agent**: Notion/Obsidian 기반 지식 저장 및 조회
*   **Research Agent**: 웹 검색 및 정보 요약
*   **File Agent**: 로컬 파일 시스템 관리
*   **Communication Agent**: Slack/Discord 메시지 연동
*   **Sandbox Agent**: 격리된 코드 실행 환경 제공

---

## 9. 문제 해결 (Troubleshooting)
*   **샌드박스 연결 실패**: `.env`의 `SANDBOX_API_KEY`가 오케스트라와 샌드박스 설정에 동일하게 반영되었는지 확인하세요.
*   **Redis 권한 오류**: `entrypoint.sh`가 정상적으로 실행되어 ACL 계정을 생성했는지 로그(`docker logs redis`)를 확인하세요.
*   **보안 로깅 확인**: API 키를 로그로 출력했을 때 마스킹되지 않는다면 `shared_core/agent_logger.py`의 패턴 설정을 확인하세요.

---
*문서 작성일: 2026-04-27*  
*관리자: 보안 및 아키텍처 팀*
