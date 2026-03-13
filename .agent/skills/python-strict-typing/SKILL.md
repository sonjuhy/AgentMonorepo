# Skill: python-strict-typing

## Description
이 스킬은 `Notion-Agent-Orchestrator` 모노리포 내에서 에이전트가 파이썬 코드를 생성, 수정, 또는 리뷰할 때 준수해야 할 엄격한 Python 3.12+ 코딩 규격과 스켈레톤(프레임) 아키텍처 원칙을 정의합니다.

## Principles (원리 및 근거)
1. **메모리 최적화 및 환각(Hallucination) 방지**: 실제 비즈니스 로직 구현을 배제하고 추상 인터페이스만 선언함으로써, 불필요한 코드 생성을 막아 토큰 낭비를 줄이고 대상 환경(128MB RAM 제한의 단발성 Docker)에 적합한 가벼운 코드를 유도합니다.
2. **정적 분석 및 타입 안정성 극대화**: PEP 695 기반의 명시적 타입 선언을 통해 코드 가독성을 높이고, 에이전트 간(예: 기획 에이전트와 코드 리뷰 에이전트) 데이터 파이프라인의 입출력 규격을 엄격하게 통제합니다.

## Rules (제약 사항)
- **Rule 1**: 모든 코드는 Python 3.12 이상 문법을 기준으로 작성하며, 레거시 타이핑 모듈(`typing.List`, `typing.Dict` 등)의 사용을 금지합니다. 내장 컬렉션(`list`, `dict`)을 직접 사용하십시오.
- **Rule 2**: 타입 별칭(Type Aliases) 선언 시 반드시 PEP 695의 `type` 키워드를 사용하십시오.
  - 올바른 예: `type TaskStatus = Literal["진행중", "완료"]`
  - 잘못된 예: `TaskStatus = Literal["진행중", "완료"]` 또는 `TaskStatus: TypeAlias = ...`
- **Rule 3**: 제네릭(Generics) 사용 시 `typing.TypeVar`를 선언하지 말고, PEP 695의 새로운 타입 파라미터 구문을 사용하십시오.
  - 올바른 예: `def process_data[T](data: T) -> list[T]:`
- **Rule 4**: 스켈레톤 코드 및 아키텍처 설계도를 코드로 변환할 때는 실제 로직을 구현하지 마십시오. `typing.Protocol` 또는 `abc.ABC`를 사용하여 인터페이스만 선언하고, 함수 본문은 `...` (Ellipsis)로 비워두십시오.
- **Rule 5**: 생성되는 모든 클래스, 메서드, 함수에는 반드시 Google Style Docstring을 포함하여 해당 코드의 목적과 파라미터, 반환 타입을 명시하십시오.

## Example: Skeleton Interface Generation
에이전트가 스켈레톤 코드를 요구받았을 때 출력해야 하는 표준 형태입니다.

```python
from typing import Protocol, Literal, Any

type AgentType = Literal["planning", "review", "summary"]
type ExecutionResult = tuple[bool, str]
type NotionPayload = dict[str, Any]

class BaseNotionAgent(Protocol):
    """
    Notion API와 통신하여 각 에이전트의 작업을 수행하는 추상 인터페이스입니다.
    
    Attributes:
        agent_type (AgentType): 현재 실행 중인 에이전트의 유형.
    """
    agent_type: AgentType

    async def fetch_pending_tasks(self) -> list[NotionPayload]:
        """
        Notion 데이터베이스에서 '검토중' 상태인 작업 목록을 폴링합니다.
        
        Returns:
            list[NotionPayload]: 파싱된 노션 작업 데이터 리스트.
        """
        ...

    async def execute_pipeline(self, task_data: NotionPayload) -> ExecutionResult:
        """
        단일 작업에 대한 에이전트 파이프라인(기획, 리뷰 등)을 실행합니다.
        
        Args:
            task_data (NotionPayload): 처리할 작업의 상세 데이터.
            
        Returns:
            ExecutionResult: 작업 성공 여부와 결과 메시지 튜플.
        """
        ...