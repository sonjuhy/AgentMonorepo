"""
VSock 길이-프리픽스 JSON 프레이밍 유틸리티

프로토콜: [uint32 BE (4바이트)][JSON payload (N바이트)]
- Firecracker VM의 virtio-vsock을 통한 호스트 ↔ 게스트 통신에 사용
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

_HEADER_FMT = ">I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

VSOCK_GUEST_PORT = 52000


async def send_json(writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack(_HEADER_FMT, len(payload))
    writer.write(header + payload)
    await writer.drain()


async def recv_json(reader: asyncio.StreamReader) -> dict[str, Any]:
    header_bytes = await asyncio.wait_for(
        reader.readexactly(_HEADER_SIZE), timeout=5.0
    )
    (length,) = struct.unpack(_HEADER_FMT, header_bytes)
    payload_bytes = await asyncio.wait_for(
        reader.readexactly(length), timeout=30.0
    )
    return json.loads(payload_bytes.decode("utf-8"))


async def open_vsock_connection(
    uds_path: str,
    port: int = VSOCK_GUEST_PORT,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Firecracker VSock UDS 프록시를 통해 guest에 연결합니다."""
    reader, writer = await asyncio.open_unix_connection(uds_path)

    writer.write(f"CONNECT {port}\n".encode())
    await writer.drain()

    ack = await asyncio.wait_for(reader.readline(), timeout=5.0)
    if not ack.startswith(b"OK "):
        writer.close()
        await writer.wait_closed()
        raise RuntimeError(f"VSock 핸드셰이크 실패: {ack!r}")

    return reader, writer
