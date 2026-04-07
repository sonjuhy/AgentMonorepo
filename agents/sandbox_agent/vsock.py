"""
VSock 길이-프리픽스 JSON 프레이밍 유틸리티

프로토콜: [uint32 BE (4바이트)][JSON payload (N바이트)]
- Firecracker VM의 virtio-vsock을 통한 호스트 ↔ 게스트 통신에 사용
- 단순 recv(4096) 방식 대신 명시적 길이 프리픽스로 fragmentation 방지
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

_HEADER_FMT = ">I"   # big-endian unsigned int (4 bytes)
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

# Firecracker VSock 내 Guest Agent 리스닝 포트
VSOCK_GUEST_PORT = 52000


async def send_json(writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
    """
    딕셔너리를 JSON 직렬화하여 [uint32 BE 길이][payload] 형식으로 전송합니다.

    Args:
        writer: asyncio StreamWriter (VSock 연결)
        data: 전송할 딕셔너리
    """
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack(_HEADER_FMT, len(payload))
    writer.write(header + payload)
    await writer.drain()


async def recv_json(reader: asyncio.StreamReader) -> dict[str, Any]:
    """
    [uint32 BE 길이][payload] 형식의 메시지를 수신하고 JSON 역직렬화합니다.

    Args:
        reader: asyncio StreamReader (VSock 연결)

    Returns:
        역직렬화된 딕셔너리

    Raises:
        asyncio.TimeoutError: 헤더/페이로드 수신 타임아웃
        json.JSONDecodeError: JSON 파싱 실패
        asyncio.IncompleteReadError: 연결이 예상보다 일찍 닫힌 경우
    """
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
    """
    Firecracker VSock UDS 프록시를 통해 guest에 연결합니다.

    Firecracker UDS 핸드셰이크 프로토콜:
      Host → "CONNECT {port}\\n"
      Host ← "OK {local_port}\\n"
    핸드셰이크 완료 후 일반 스트림처럼 send_json / recv_json을 사용합니다.

    Args:
        uds_path: Firecracker VSock UDS 소켓 경로 (예: /tmp/fc-vsock-abc123.sock)
        port: guest agent 리스닝 포트 (기본: VSOCK_GUEST_PORT=52000)

    Returns:
        (reader, writer) 튜플

    Raises:
        RuntimeError: 핸드셰이크 실패
        asyncio.TimeoutError: 응답 타임아웃
    """
    reader, writer = await asyncio.open_unix_connection(uds_path)

    # Firecracker UDS 핸드셰이크
    writer.write(f"CONNECT {port}\n".encode())
    await writer.drain()

    ack = await asyncio.wait_for(reader.readline(), timeout=5.0)
    if not ack.startswith(b"OK "):
        writer.close()
        await writer.wait_closed()
        raise RuntimeError(f"VSock 핸드셰이크 실패: {ack!r}")

    return reader, writer
