# Redis ACL 설정 — 에이전트별 접근 권한 격리 (보안 강화)
#
# 계정 구조:
#   orchestra  — 오케스트라 에이전트 전용. 전체 키 접근 허용.
#   {agent}    — 각 하위 에이전트 전용 계정. 자신의 큐·헬스만 허용.
#
# 환경변수:
#   REDIS_ORCHESTRA_PASSWORD — orchestra 계정 비밀번호 (필수)
#   REDIS_COMMUNITY_PASSWORD — 모든 하위 에이전트 공통 비밀번호 (템플릿용)

# 기본 계정 비활성화 (익명 접근 차단)
user default off nopass nocommands nokeys

# ── orchestra: 오케스트라 에이전트 전용 (전체 접근) ──────────────────────────
user orchestra on >ORCHESTRA_PASSWORD_PLACEHOLDER ~* &* +@all

# ── community: 하위 호환성용 (광범위 와일드카드 제거) ────────────────────────
# 기존 에이전트들이 community 계정을 사용할 경우를 위해 남겨두되, 
# agent:*:tasks 와 같은 와일드카드는 제거하여 다른 에이전트 침범을 방지합니다.
user community on >COMMUNITY_PASSWORD_PLACEHOLDER \
  ~orchestra:results:* \
  ~orchestra:dlq \
  resetchannels \
  +rpush \
  +llen

# ── 하위 에이전트별 계정은 entrypoint.sh에서 동적 생성됩니다 ──────────────────
# 생성 규칙: user {name} on >{PASS} ~agent:{name}:tasks ~agent:{name}:health ...
