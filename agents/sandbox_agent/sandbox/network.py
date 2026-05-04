"""
TAP 네트워크 인터페이스 관리 (Firecracker VM용)

각 Firecracker VM은 전용 TAP 디바이스를 가집니다:
- VM → 호스트 트래픽만 허용 (인터넷 완전 차단)
- ip tuntap / iptables 명령 기반
- Linux 전용 (컨테이너 환경 내에서 실행)
"""

from __future__ import annotations

import asyncio
import logging
from ipaddress import IPv4Network

logger = logging.getLogger("cassiopeia_agent.sandbox.network")

_BASE_SUBNET = "172.16.0.0/16"


class TAPInterface:
    """Firecracker VM용 TAP 디바이스 생성 및 정리."""

    def __init__(self, vm_id: str) -> None:
        self._vm_id = vm_id
        self._tap_name = f"tap{vm_id[:11]}"
        self._host_ip: str | None = None
        self._vm_ip: str | None = None

    @property
    def tap_name(self) -> str:
        return self._tap_name

    @property
    def host_ip(self) -> str | None:
        return self._host_ip

    @property
    def vm_ip(self) -> str | None:
        return self._vm_ip

    async def setup(self) -> str:
        subnet_index = int(self._vm_id[:4], 16) % 16384
        base_net = IPv4Network(_BASE_SUBNET)
        subnets = list(base_net.subnets(new_prefix=30))
        subnet = subnets[subnet_index % len(subnets)]
        hosts = list(subnet.hosts())
        self._host_ip = str(hosts[0])
        self._vm_ip = str(hosts[1])

        cmds = [
            ["ip", "tuntap", "add", "dev", self._tap_name, "mode", "tap"],
            ["ip", "addr", "add", f"{self._host_ip}/30", "dev", self._tap_name],
            ["ip", "link", "set", "dev", self._tap_name, "up"],
            ["iptables", "-I", "FORWARD", "-i", self._tap_name, "-d", self._host_ip, "-j", "ACCEPT"],
            ["iptables", "-I", "FORWARD", "-i", self._tap_name, "!", "-d", self._host_ip, "-j", "DROP"],
        ]

        for cmd in cmds:
            await self._run(cmd)

        logger.debug("[TAPInterface] TAP 설정 완료: %s (host=%s, vm=%s)", self._tap_name, self._host_ip, self._vm_ip)
        return self._tap_name

    async def teardown(self) -> None:
        cmds: list[list[str]] = []
        if self._host_ip:
            cmds += [
                ["iptables", "-D", "FORWARD", "-i", self._tap_name, "-d", self._host_ip, "-j", "ACCEPT"],
                ["iptables", "-D", "FORWARD", "-i", self._tap_name, "!", "-d", self._host_ip, "-j", "DROP"],
            ]
        cmds.append(["ip", "link", "delete", "dev", self._tap_name])

        for cmd in cmds:
            try:
                await self._run(cmd)
            except Exception as exc:
                logger.warning("[TAPInterface] teardown 실패 (%s): %s", cmd, exc)

        logger.debug("[TAPInterface] TAP 정리 완료: %s", self._tap_name)

    @staticmethod
    async def _run(cmd: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"명령 실패 {cmd}: {stderr.decode().strip()}")
