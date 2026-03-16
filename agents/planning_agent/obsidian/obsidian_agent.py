"""
Obsidian Planning Agent 프레임워크 스켈레톤
- 로컬 마크다운 파일(Obsidian Vault) 연동을 위한 에이전트 인터페이스
"""

import os
import glob
from typing import Any

from ..models import ExecutionResult, ParsedTask, RawPayload
from ..protocols import PlanningAgentProtocol

class ObsidianPlanningAgent(PlanningAgentProtocol):
    """
    Obsidian 볼트 내의 마크다운 파일을 파싱하여 기획 태스크를 수행하는 에이전트.
    """
    
    agent_name: str = "obsidian-planning-agent"

    def __init__(self, vault_path: str, task_folder: str = "Tasks/Planning") -> None:
        """
        초기화 시 타겟 볼트 폴더 경로를 설정합니다.
        
        Args:
            vault_path (str): 옵시디언 볼트의 루트 절대 경로
            task_folder (str): 태스크 파일들이 위치한 하위 폴더 경로
        """
        self.vault_path = vault_path
        self.target_dir = os.path.join(self.vault_path, task_folder)
        
        if not os.path.exists(self.target_dir):
            pass # TODO: 로깅 또는 예외 처리

    async def fetch_pending_tasks(self) -> list[RawPayload]:
        """
        지정된 볼트 폴더에서 마크다운 파일들의 목록과 내용을 읽어옵니다.
        
        로직 흐름:
        1. target_dir 내의 모든 .md 파일 검색
        2. 파일을 열어 내용을 읽고, Frontmatter(YAML) 영역 추출
        3. status 등 특정 메타데이터 조건을 만족하는 파일만 필터링하여 리스트로 반환
        
        Returns:
            list[RawPayload]: 각 파일의 파싱 전 가공 정보 리스트 (경로, 메타데이터, 텍스트 본문 등 포함)
        """
        pending_tasks = []
        # TODO: 파일 시스템 스캔 및 필터링 로직 구현 (os.walk 또는 glob)
        return pending_tasks

    async def _parse_frontmatter(self, file_content: str) -> dict[str, Any]:
        """
        마크다운 파일 내용에서 YAML Frontmatter를 추출하고 파싱하는 유틸리티 메서드 (내부 구현용).
        정규식표현식(re) 또는 yaml 모듈 사용 권장.
        """
        pass

    async def parse_obsidian_task(self, raw_data: RawPayload) -> ParsedTask | None:
        """
        옵시디언 마크다운 파일 구조에서 표준 포맷인 `ParsedTask`로 데이터를 매핑합니다.
        노션의 `parse_notion_task`와 유사한 역할을 수행합니다.
        
        Args:
            raw_data (RawPayload): 마크다운 파일 경로와 내용, 메타데이터 등이 담긴 딕셔너리
            
        Returns:
            ParsedTask | None: 파싱 성공 시 표준 포맷 딕셔너리, 실패/누락 시 None
        """
        # TODO: raw_data 내의 메타데이터를 ParsedTask 필드에 맞게 변환
        pass

    async def update_obsidian_task(
        self,
        filepath: str,
        status: str | None = None,
        agent_names: list[str] | None = None,
        design_doc: str | None = None,
        skeleton_code: str | None = None,
    ) -> ExecutionResult:
        """
        타겟 마크다운 파일의 내용을 갱신합니다.
        
        로직 흐름:
        1. filepath에서 파일 내용을 읽습니다.
        2. status, agent_names 등의 변경사항을 Frontmatter에 덮어씁니다.
        3. design_doc, skeleton_code 등을 마크다운 본문에 적절하게 어펜드(append)합니다.
        4. 변경된 내용으로 파일을 다시 저장합니다.
        
        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        # TODO: 파일 읽기 -> 메타데이터/본문 수정 -> 파일 쓰기 로직 구현
        return (True, f"옵시디언 파일 업데이트 성공: {filepath}")

    async def process_task(self, task_data: ParsedTask) -> ExecutionResult:
        """
        추출된 태스크를 기반으로 실제 기획 에이전트 핵심 처리를 수행합니다.
        부모 추상 인터페이스인 `PlanningAgentProtocol`의 요구사항을 만족합니다.
        
        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        try:
            print(f"[{self.agent_name}] 옵시디언 태스크 처리 중: [{task_data.get('status')}] {task_data.get('title')}")
            # TODO: LLM 연동, 문서 작성 로직 등 핵심 처리부
            return (True, f"옵시디언 태스크 처리 완료: {task_data.get('page_id')}") # page_id 는 파일명 혹은 경로
        except Exception as e:
            return (False, f"옵시디언 태스크 처리 실패: {e}")

    async def run(self) -> None:
        """
        옵시디언 기획 에이전트의 단발성 실행 라이프사이클을 돌립니다.
        
        순서: 
        조회(fetch) -> 파싱(parse) -> 처리(process) -> 업데이트(update) -> 결과 출력 -> 종료
        """
        print(f"[{self.agent_name}] 실행 시작 (Vault: {self.vault_path})")
        
        raw_tasks = await self.fetch_pending_tasks()
        print(f"[{self.agent_name}] 조회된 옵시디언 태스크 수: {len(raw_tasks)}")
        
        for raw in raw_tasks:
            task = await self.parse_obsidian_task(raw)
            if task is None:
                continue

            success, message = await self.process_task(task)
            status_label = "완료" if success else "실패"
            print(f"[{self.agent_name}] {status_label}: {message}")
            
            # TODO: 처리 완료 후 update_obsidian_task 호출하여 실제 파일 변경 반영
            
        print(f"[{self.agent_name}] 실행 종료")
