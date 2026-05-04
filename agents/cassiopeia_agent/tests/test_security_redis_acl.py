import pytest
import re
from pathlib import Path

def test_redis_acl_restriction():
    """
    Redis ACL 설정 파일이 'community' 계정에 대해 광범위한 와일드카드(*)를 허용하지 않는지 검증합니다.
    """
    acl_path = Path("redis/acl.conf")
    if not acl_path.exists():
        # CI/CD 환경이나 로컬 테스트 시 acl.conf.tpl을 기반으로 검증 시뮬레이션
        acl_path = Path("redis/acl.conf.tpl")
        
    with open(acl_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 'user community' 섹션 전체를 가져옵니다.
    sections = re.split(r'\n(?=user )', content)
    community_section = next((s for s in sections if s.startswith("user community")), None)
    
    assert community_section is not None, "community 유저 설정이 acl.conf에 없습니다."
    
    # 보안 취약점 점검: agent:*:tasks 또는 agent:*:health 와 같은 광범위한 와일드카드 확인
    broad_patterns = re.findall(r"~agent:\*:tasks|~agent:\*:health", community_section)
    
    assert len(broad_patterns) == 0, (
        f"보안 취약점 발견: community 계정이 모든 에이전트의 큐에 접근 가능합니다. ({broad_patterns})\n"
        "에이전트별로 전용 계정을 생성하거나, 접근 범위를 더 제한해야 합니다."
    )

def test_orchestra_is_only_full_access():
    """orchestra 계정만 전체 접근(*) 권한을 가져야 함을 검증합니다."""
    acl_path = Path("redis/acl.conf")
    if not acl_path.exists():
        acl_path = Path("redis/acl.conf.tpl")

    with open(acl_path, "r", encoding="utf-8") as f:
        content = f.read()

    sections = re.split(r'\n(?=user )', content)
    
    full_access_users = []
    for section in sections:
        if "~*" in section:
            user_match = re.match(r"user (\w+)", section)
            if user_match:
                full_access_users.append(user_match.group(1))
    
    assert full_access_users == ["orchestra"], f"orchestra 외에 전체 권한을 가진 유저가 있습니다: {full_access_users}"
