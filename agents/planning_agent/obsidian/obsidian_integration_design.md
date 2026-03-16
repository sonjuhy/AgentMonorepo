# 옵시디언 통신 기능 설명서 (Obsidian Integration Design)

본 문서는 `PlanningAgent`를 기존의 노션(Notion) 통신 기반에서, 마크다운 기반의 로컬 노트 애플리케이션인 **Obsidian**과도 통신하여 기획 태스크를 처리할 수 있게 하는 프레임워크와 주요 기능 설계 방향을 서술합니다.

## 핵심 목표
1. **로컬 파일 시스템 접근**: API 통신(`htppx`) 중심인 노션과 달리, 지정된 경로의 마크다운 파일(`.md`)을 직접 읽고 씁니다.
2. **단발성 파이프라인 유지**: 기존의 파이프라인 구조(`PlanningAgentProtocol`: `fetch` -> `parse` -> `process` -> `update` -> 종료)를 유지합니다. (ephemeral-docker-ops 원칙)
3. **메타데이터 파싱**: 노션의 프로퍼티 역할을 하는 옵시디언의 YAML Frontmatter(헤더 메타데이터)를 파싱하고 수정하는 구조를 만듭니다.

## 데이터 구조 매핑

| 기능 / 데이터 | Notion (기존) | Obsidian (신규 제안) | 비고 |
| :--- | :--- | :--- | :--- |
| **태스크 고유 ID** | `page_id` (고유 문자열 ID) | 파일의 '절대 경로' 또는 파일명(`filepath`) | 파일명 자체가 ID 역할을 수행할 수 있음 |
| **조회(Fetch)** | `httpx.post(url, query...)` | `os.walk` 또는 `glob.glob` 탐색 | 로컬 디렉토리 내 `.md` 파일 대상 |
| **메타데이터 보관** | `properties` (JSON) | YAML Frontmatter (`---` 구역) | 파싱용 라이브러리(`pyyaml` 등) 도입 검토 |
| **본문(Content)** | `rich_text` 블록 구조 | 순수 마크다운 본문 텍스트 통짜 | 본문 추가/수정이 훨씬 직관적임 |
| **상태 관리** | `status` 프로퍼티 (기획중, 완료) | Frontmatter 내 `status: 기획중` | 정규 표현식으로 파싱할 수도 있음 |

## 워크플로우 명세 (프레임워크)

### 1. `fetch_pending_tasks(self) -> list[RawPayload]`
*   **실행**: 타겟 옵시디언 볼트(Vault) 폴더 경로를 스캔합니다.
*   **필터링**: 마크다운 파일의 내용을 읽고, Frontmatter 내에 `status: 검토중` (또는 `기획중`) 등 지정된 실행 조건이 있는지 확인합니다.
*   **반환**: 조건에 맞는 파일들의 경로, 메타데이터 구조체 및 원본 문자열을 포함하는 로우 포맷 리스트를 넘깁니다.

### 2. `parse_task(self, raw: dict) -> ParsedTask`
*   **실행**: 읽어들인 마크다운의 메타데이터를 표준화된 포맷(`models.py`의 `ParsedTask`)으로 변환합니다.
*   **반환**: 표준 포맷. 이 단계에서 인터페이스가 일치되므로 `process_task` 부분 로직은 거의 재활용이 가능합니다.

### 3. `process_task(self, task: ParsedTask) -> ExecutionResult`
*   이 부분은 인공지능이 개입하는 기획 처리 본연의 로직으로, 노션과 옵시디언 구분 없이 **공통 로직**으로 사용할 수 있습니다.

### 4. `update_obsidian_task(self, filepath, updates...) -> ExecutionResult`
*   **실행**: 처리가 끝난 후, 대상 마크다운 파일의 Frontmatter를 갱신합니다. 예로 `status: 완료` 변경 및 본문에 기획 결과 내용(`기획안/설계도`, `스켈레톤 코드` 섹션 등)을 마크다운 포맷으로 어펜드(append)하여 씁니다.

## 기술적 고려사항 및 제약
1. **동시성(Concurrency) 한계**: 옵시디언은 로컬 파일이므로, 에이전트가 파일을 읽고 쓰는 도중 유저가 옵시디언 앱에서 해당 파일을 동시에 수정하면 충돌(Conflict)이 발생할 수 있습니다.
2. **파서의 종류**: 파싱을 위해 파이썬 내장 라이브러리(`re` 기반 정규식)만 쓸지, `python-frontmatter` 등 외부 패키지에 의존할지 선택해야 합니다. 최소 의존성을 위해 `re`와 `yaml` 결합 사용을 추천합니다.
