#!/usr/bin/env bash
# Firecracker rootfs.ext4 빌드 스크립트
#
# 사용법:
#   ./build_rootfs.sh [출력_디렉터리]
#   기본 출력 디렉터리: /opt/firecracker/
#
# 요구사항:
#   - Docker        : Alpine 파일시스템 구성
#   - e2fsprogs     : mkfs.ext4 (Ubuntu: apt install e2fsprogs)
#   - sudo          : loop 마운트 권한
#   - Firecracker 커널 이미지는 별도로 다운로드 필요
#
# 커널 다운로드 (예시):
#   FC_VER="v1.9.0"
#   curl -L "https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.9/x86_64/vmlinux-5.10.225" \
#        -o /opt/firecracker/vmlinux
#
# 환경변수:
#   ROOTFS_SIZE_MB  : rootfs 크기(MB), 기본 512
#   OUTPUT_DIR      : 출력 디렉터리, 기본 /opt/firecracker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${1:-/opt/firecracker}"
ROOTFS_SIZE_MB="${ROOTFS_SIZE_MB:-512}"
IMAGE_PATH="$OUTPUT_DIR/rootfs.ext4"

echo "=== Firecracker rootfs 빌드 ==="
echo "  출력 경로  : $IMAGE_PATH"
echo "  크기       : ${ROOTFS_SIZE_MB}MB"
echo "  소스       : $SCRIPT_DIR"
echo ""

# ── 1. Docker 이미지 빌드 ────────────────────────────────────────────────────
echo "[1/4] Docker 이미지 빌드 (sandbox-rootfs-builder:latest)..."
docker build \
    --no-cache \
    -t sandbox-rootfs-builder:latest \
    -f "$SCRIPT_DIR/Dockerfile.rootfs" \
    "$SCRIPT_DIR"

# ── 2. 파일시스템 추출 ────────────────────────────────────────────────────────
echo "[2/4] Alpine 파일시스템 추출..."
TMP_FS=$(mktemp -d)
trap "rm -rf '$TMP_FS'" EXIT

CONTAINER_ID=$(docker create sandbox-rootfs-builder:latest)
docker export "$CONTAINER_ID" | tar -x -C "$TMP_FS"
docker rm "$CONTAINER_ID" > /dev/null
echo "      파일시스템 추출 완료: $TMP_FS"

# ── 3. ext4 이미지 생성 ──────────────────────────────────────────────────────
echo "[3/4] ext4 이미지 생성 (${ROOTFS_SIZE_MB}MB)..."
mkdir -p "$OUTPUT_DIR"
dd if=/dev/zero of="$IMAGE_PATH" bs=1M count="$ROOTFS_SIZE_MB" status=progress
mkfs.ext4 -F -L rootfs "$IMAGE_PATH"

# ── 4. 파일시스템 복사 ───────────────────────────────────────────────────────
echo "[4/4] 파일시스템 복사..."
TMP_MOUNT=$(mktemp -d)
trap "sudo umount '$TMP_MOUNT' 2>/dev/null || true; rm -rf '$TMP_FS' '$TMP_MOUNT'" EXIT

sudo mount -o loop "$IMAGE_PATH" "$TMP_MOUNT"
sudo cp -a "$TMP_FS"/. "$TMP_MOUNT"/
sudo umount "$TMP_MOUNT"
rm -rf "$TMP_MOUNT"
trap "rm -rf '$TMP_FS'" EXIT   # umount 완료 후 trap 재설정

# ── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== 빌드 완료 ==="
echo "rootfs.ext4 : $IMAGE_PATH ($(du -sh "$IMAGE_PATH" | cut -f1))"
echo ""
echo "환경변수 설정:"
echo "  export FIRECRACKER_ROOTFS=$IMAGE_PATH"
echo ""
echo "커널 이미지가 없으면 다운로드 후 설정하세요:"
echo "  curl -L 'https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.9/x86_64/vmlinux-5.10.225' \\"
echo "       -o $OUTPUT_DIR/vmlinux"
echo "  export FIRECRACKER_KERNEL=$OUTPUT_DIR/vmlinux"
