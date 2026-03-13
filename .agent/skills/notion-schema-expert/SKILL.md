# Skill: notion-schema-expert

## Description
이 스킬은 `Notion-Agent-Orchestrator` 모노리포 환경에서 에이전트가 Notion API와 통신할 때, 복잡한 JSON 페이로드(Payload)를 정확히 파싱하고 시스템 내부의 데이터베이스 스키마와 동기화하기 위한 표준 규격을 정의합니다.

## Principles (원리 및 근거)
1. **결정론적(Deterministic) 데이터 매핑**: Notion 페이지 속성(Properties)은 단순 키-값 쌍이 아니라 깊은 중첩 딕셔너리(Deeply nested dictionary) 구조입니다. 에이전트의 기계적 환각을 방지하고 런타임 에러(KeyError)를 차단하기 위해, 추측성 파싱을 금지하고 명시된 스키마 구조에 기반한 안전한 데이터 추출 로직을 강제합니다.
2. **API 버저닝 안정성**: Notion API는 버전마다 응답 규격이 미세하게 다릅니다. 이 스킬은 안정성이 검증된 `Notion-Version: 2022-06-28` 스펙을 기준으로 작동하도록 고정하여, 에이전트 간 통신 규격을 통일합니다.

## Rules (제약 사항)
- **Rule 1**: Notion API 요청 시 HTTP 헤더에 반드시 `"Notion-Version": "2022-06-28"`을 포함하십시오.
- **Rule 2**: 페이지 속성(Properties)을 읽어올 때, 딕셔너리의 직접 접근(예: `data["properties"]["제목"]["title"][0]["plain_text"]`)은 금지됩니다. 반드시 `dict.get()` 체이닝이나 예외 처리를 사용하여 `IndexError` 및 `KeyError` 발생을 원천 차단하십시오.
- **Rule 3**: 파싱된 데이터 모델을 정의할 때는 Python 3.12의 `type` 키워드를 활용한 타입 별칭과 `typing.TypedDict` 또는 파이썬의 `dataclasses.dataclass`를 사용하여 반환 구조를 명확히 하십시오.
- **Rule 4**: 본 프로젝트의 주요 속성 타입 매핑 공식은 다음과 같습니다. 데이터베이스 스키마가 변경되지 않는 한 이 구조를 엄격히 따르십시오.
  - `title` 필드 -> `properties["제목"]["title"][0]["plain_text"]`
  - `rich_text` 필드 -> `properties["목적"]["rich_text"][0]["plain_text"]`
  - `status` 필드 -> `properties["현황"]["status"]["name"]`

## Example: Safe Payload Parsing
다음은 에이전트가 Notion API JSON 응답을 파싱할 때 작성해야 하는 Python 3.12+ 기반의 안전한 파싱 구조 및 타입 힌트 예시입니다.

```python
from typing import Any, TypedDict

# Python 3.12: PEP 695 Type Aliases
type RawPayload = dict[str, Any]
type PageId = str

class ParsedTask(TypedDict):
    """파싱 완료된 노션 태스크의 표준 데이터 구조"""
    page_id: PageId
    title: str
    description: str
    status: str

def parse_notion_task(payload: RawPayload) -> ParsedTask | None:
    """
    Notion API의 복잡한 JSON 페이로드에서 필요한 속성을 안전하게 추출합니다.
    
    Args:
        payload (RawPayload): Notion API로부터 반환된 단일 페이지 객체.
        
    Returns:
        ParsedTask | None: 파싱 성공 시 딕셔너리 반환, 필수 필드 누락/오류 시 None 반환.
    """
    try:
        page_id: str = payload["id"]
        properties: dict[str, Any] = payload.get("properties", {})
        
        # Rule 2 적용: 중첩된 JSON 구조를 안전하게 탐색 (KeyError 및 IndexError 방지)
        title_list: list[dict[str, Any]] = properties.get("제목", {}).get("title", [])
        title: str = title_list[0].get("plain_text", "제목 없음") if title_list else "제목 없음"
        
        desc_list: list[dict[str, Any]] = properties.get("목적", {}).get("rich_text", [])
        description: str = desc_list[0].get("plain_text", "") if desc_list else ""
        
        status_obj: dict[str, Any] = properties.get("현황", {}).get("status", {})
        status: str = status_obj.get("name", "상태 미상")
        
        return {
            "page_id": page_id,
            "title": title,
            "description": description,
            "status": status
        }
    except Exception as e:
        # 실무 적용 시 logger 모듈로 대체
        print(f"페이로드 파싱 실패: {e}")
        return None