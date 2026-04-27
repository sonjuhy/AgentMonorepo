#!/bin/sh
# Redis ACL 파일의 비밀번호 플레이스홀더를 환경변수로 치환하고 에이전트별 계정을 생성한 뒤 Redis를 시작합니다.
set -e

: "${REDIS_ORCHESTRA_PASSWORD:?REDIS_ORCHESTRA_PASSWORD 환경변수가 설정되지 않았습니다}"
: "${REDIS_COMMUNITY_PASSWORD:?REDIS_COMMUNITY_PASSWORD 환경변수가 설정되지 않았습니다}"

# 1. 템플릿 복사 및 기본 계정 비밀번호 치환
sed \
  -e "s/ORCHESTRA_PASSWORD_PLACEHOLDER/${REDIS_ORCHESTRA_PASSWORD}/g" \
  -e "s/COMMUNITY_PASSWORD_PLACEHOLDER/${REDIS_COMMUNITY_PASSWORD}/g" \
  /etc/redis/acl.conf.tpl > /etc/redis/acl.conf

# 2. 에이전트별 전용 계정 추가 (보안 격리)
# 에이전트는 본인의 큐(agent:{name}:tasks)와 헬스(agent:{name}:health)에만 접근할 수 있습니다.
AGENTS="planning slack file research schedule archive sandbox communication"

for name in $AGENTS; do
  echo "user $name on >${REDIS_COMMUNITY_PASSWORD} ~agent:$name:tasks ~agent:$name:health ~orchestra:results:* ~orchestra:dlq resetchannels +blpop +rpush +hset +hgetall +expire +llen" >> /etc/redis/acl.conf
done

echo "[Entrypoint] Redis ACL 설정 완료 (에이전트별 격리 적용)"

exec redis-server \
  --appendonly yes \
  --maxmemory 512mb \
  --maxmemory-policy allkeys-lru \
  --aclfile /etc/redis/acl.conf \
  "$@"
