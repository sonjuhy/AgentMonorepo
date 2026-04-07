"""
Firecracker MicroVM 기반 격리 샌드박스

KVM 하드웨어 가상화를 이용한 최고 수준의 격리 실행 환경:
- 부팅 시간 ~50ms
- 전용 TAP 네트워크 + VSock 통신
- 태스크 완료 후 VM 즉시 폐기 (ephemeral, 재사용 불가)
- VM 내 guest agent가 VSock을 통해 코드를 수신하고 실행 결과를 반환

Guest Agent 프로토콜 (VSock JSON):
    요청: {"language": str, "code": str, "stdin": str, "timeout": int, "env": dict}
    응답: {"stdout": str, "stderr": str, "exit_code": int}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from .models import ExecuteRequest, SandboxTaskResult
from .network import TAPInterface
from .vsock import open_vsock_connection, recv_json, send_json

logger = logging.getLogger("sandbox_agent.firecracker")

_FIRECRACKER_BIN = os.environ.get("FIRECRACKER_BIN", "/usr/local/bin/firecracker")
_KERNEL_IMAGE = os.environ.get("FIRECRACKER_KERNEL", "/opt/firecracker/vmlinux")
_ROOTFS_IMAGE = os.environ.get("FIRECRACKER_ROOTFS", "/opt/firecracker/rootfs.ext4")
_VCPU_COUNT = int(os.environ.get("FIRECRACKER_VCPU", "1"))

# Firecracker API 소켓 경로 템플릿
_API_SOCKET_TPL = "/tmp/fc-api-{vm_id}.sock"
# VSock 호스트 측 소켓 경로 템플릿
_VSOCK_SOCKET_TPL = "/tmp/fc-vsock-{vm_id}.sock"
# VM 내 VSock CID (고정값 — 각 VM은 별도 소켓 파일로 격리됨)
_VSOCK_GUEST_CID = 3


class FirecrackerSandbox:
    """
    Firecracker MicroVM 기반 격리 실행 환경.

    사용법:
        sandbox = FirecrackerSandbox()
        await sandbox.start()
        result = await sandbox.execute(req)
        await sandbox.close()
    """

    def __init__(self) -> None:
        self.vm_id = str(uuid.uuid4())[:8]
        self._process: asyncio.subprocess.Process | None = None
        self._tap: TAPInterface | None = None
        self._api_socket = _API_SOCKET_TPL.format(vm_id=self.vm_id)
        self._vsock_path = _VSOCK_SOCKET_TPL.format(vm_id=self.vm_id)

    async def start(self) -> None:
        """
        VM을 부팅합니다.

        순서:
          1. TAP 네트워크 설정
          2. Firecracker 프로세스 시작
          3. API 소켓을 통해 VM 설정 (kernel, rootfs, vsock, network)
          4. VM 인스턴스 시작 → guest agent 부팅 대기
        """
        logger.info("[FirecrackerSandbox] VM 부팅 시작: vm_id=%s", self.vm_id)
        start_ms = time.monotonic()

        # TAP 설정 (Linux에서만 동작)
        try:
            self._tap = TAPInterface(self.vm_id)
            await self._tap.setup()
        except Exception as exc:
            logger.warning(
                "[FirecrackerSandbox] TAP 설정 실패 (vm_id=%s): %s — 네트워크 없이 계속",
                self.vm_id, exc,
            )
            self._tap = None

        # Firecracker 프로세스 시작
        self._process = await asyncio.create_subprocess_exec(
            _FIRECRACKER_BIN,
            "--api-sock", self._api_socket,
            "--log-level", "Error",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # API 소켓 생성 대기 (최대 2초)
        await self._wait_socket(self._api_socket, timeout=2.0)

        # VM 설정 (kernel, rootfs, vsock, network interface)
        await self._configure_vm()

        # VSock 소켓 생성 대기 (최대 3초)
        await self._wait_socket(self._vsock_path, timeout=3.0)

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        logger.info(
            "[FirecrackerSandbox] VM 부팅 완료: vm_id=%s (%dms)",
            self.vm_id, elapsed_ms,
        )

    async def execute(self, req: ExecuteRequest) -> SandboxTaskResult:
        """
        VSock을 통해 guest agent에 실행 요청을 전송하고 결과를 수신합니다.

        Args:
            req: 실행 요청

        Returns:
            SandboxTaskResult
        """
        if not Path(self._vsock_path).exists():
            raise RuntimeError(f"VSock 소켓 없음: {self._vsock_path}")

        start_ms = time.monotonic()
        logger.debug(
            "[FirecrackerSandbox] 실행 요청: vm_id=%s lang=%s",
            self.vm_id, req.language,
        )

        reader, writer = await open_vsock_connection(self._vsock_path)
        try:
            await send_json(writer, {
                "language": req.language,
                "code": req.code,
                "stdin": req.stdin,
                "timeout": req.timeout,
                "env": req.env,
            })

            response = await asyncio.wait_for(
                recv_json(reader),
                timeout=req.timeout + 10,
            )
        finally:
            writer.close()
            await writer.wait_closed()

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        return SandboxTaskResult(
            stdout=response.get("stdout", ""),
            stderr=response.get("stderr", ""),
            exit_code=response.get("exit_code", -1),
            runtime_used="firecracker",
            execution_time_ms=elapsed_ms,
        )

    async def close(self) -> None:
        """VM 프로세스를 종료하고 TAP/소켓 파일을 정리합니다."""
        logger.debug("[FirecrackerSandbox] VM 종료: vm_id=%s", self.vm_id)

        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        if self._tap:
            try:
                await self._tap.teardown()
            except Exception as exc:
                logger.warning("[FirecrackerSandbox] TAP 정리 실패: %s", exc)

        # 소켓 파일 삭제
        for path in (self._api_socket, self._vsock_path):
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    async def _configure_vm(self) -> None:
        """
        Firecracker API 소켓을 통해 VM을 설정하고 인스턴스를 시작합니다.

        Firecracker REST API:
          PUT /boot-source    → 커널 및 커맨드라인
          PUT /drives/rootfs  → 루트 파일시스템
          PUT /vsock          → VSock 디바이스
          PUT /network-interfaces/eth0 → TAP 네트워크
          PUT /actions        → InstanceStart
        """
        import socket

        async def api_put(path: str, body: dict) -> None:
            """Unix 소켓 기반 Firecracker API PUT 요청."""
            # asyncio에는 기본 Unix HTTP 클라이언트가 없으므로 raw socket 사용
            request_body = json.dumps(body).encode()
            request = (
                f"PUT {path} HTTP/1.1\r\n"
                f"Host: localhost\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(request_body)}\r\n"
                f"\r\n"
            ).encode() + request_body

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.setblocking(False)
            loop = asyncio.get_event_loop()
            await loop.sock_connect(sock, self._api_socket)
            await loop.sock_sendall(sock, request)
            # 응답 읽기 (상태 코드 확인 생략 — 오류는 VM 시작 시 드러남)
            await loop.sock_recv(sock, 4096)
            sock.close()

        vcpu_count = _VCPU_COUNT
        memory_size_mib = 128  # guest agent 전용 최소 메모리

        # 1. 커널 설정
        await api_put("/boot-source", {
            "kernel_image_path": _KERNEL_IMAGE,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off nomodules rw init=/init",
        })

        # 2. 루트 파일시스템
        await api_put("/drives/rootfs", {
            "drive_id": "rootfs",
            "path_on_host": _ROOTFS_IMAGE,
            "is_root_device": True,
            "is_read_only": True,
        })

        # 3. VSock 디바이스
        await api_put("/vsock", {
            "guest_cid": _VSOCK_GUEST_CID,
            "uds_path": self._vsock_path,
        })

        # 4. 네트워크 인터페이스 (TAP 설정 성공 시)
        if self._tap and self._tap.host_ip:
            await api_put("/network-interfaces/eth0", {
                "iface_id": "eth0",
                "guest_mac": f"AA:FC:{self.vm_id[:2]}:{self.vm_id[2:4]}:{self.vm_id[4:6]}:{self.vm_id[6:8]}",
                "host_dev_name": self._tap.tap_name,
            })

        # 5. 머신 설정
        await api_put("/machine-config", {
            "vcpu_count": vcpu_count,
            "mem_size_mib": memory_size_mib,
        })

        # 6. VM 시작
        await api_put("/actions", {"action_type": "InstanceStart"})

    @staticmethod
    async def _wait_socket(path: str, timeout: float = 3.0) -> None:
        """
        소켓 파일이 생성될 때까지 대기합니다.

        Args:
            path: 소켓 파일 경로
            timeout: 최대 대기 시간(초)

        Raises:
            asyncio.TimeoutError: 타임아웃 초과
        """
        deadline = time.monotonic() + timeout
        while not Path(path).exists():
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError(f"소켓 파일 생성 타임아웃: {path}")
            await asyncio.sleep(0.05)
