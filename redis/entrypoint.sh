#!/bin/sh
set -e

: "${REDIS_CASSIOPEIA_PASSWORD:?REDIS_CASSIOPEIA_PASSWORD env var is not set}"
: "${REDIS_COMMUNITY_PASSWORD:?REDIS_COMMUNITY_PASSWORD env var is not set}"

sed \
  -e "s/CASSIOPEIA_PASSWORD_PLACEHOLDER/${REDIS_CASSIOPEIA_PASSWORD}/g" \
  -e "s/COMMUNITY_PASSWORD_PLACEHOLDER/${REDIS_COMMUNITY_PASSWORD}/g" \
  -e '/^[[:space:]]*#/d' \
  -e '/^[[:space:]]*$/d' \
  /etc/redis/acl.conf.tpl > /etc/redis/acl.conf

AGENTS="planning slack file research schedule archive sandbox communication"

for name in $AGENTS; do
  echo "user $name on >${REDIS_COMMUNITY_PASSWORD} ~agent:$name:tasks ~agent:$name:health ~cassiopeia:results:* ~cassiopeia:dlq resetchannels +blpop +rpush +hset +hgetall +expire +llen" >> /etc/redis/acl.conf
done

echo "[Entrypoint] Redis ACL setup complete"

exec redis-server \
  --appendonly yes \
  --maxmemory 512mb \
  --maxmemory-policy allkeys-lru \
  --aclfile /etc/redis/acl.conf \
  "$@"
