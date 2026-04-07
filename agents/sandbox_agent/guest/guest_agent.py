#!/usr/bin/env python3
"""
Sandbox VM Guest Agent

Firecracker VM 내부에서 실행됩니다.
AF_VSOCK으로 호스트의 코드 실행 요청을 수신하고 결과를 반환합니다.

프로토콜 (vsock.py와 동일한 길이-프리픽스 JSON):
    요청: {"language": str, "code": str, "stdin": str, "timeout": int, "env": dict}
    응답: {"stdout": str, "stderr": str, "exit_code": int}

VSock 설정:
    - Guest CID: Firecracker에서 설정한 guest_cid (기본 3)
    - Port: 52000 (VSOCK_GUEST_PORT)
    - 호스트가 UDS 프록시를 통해 연결을 시작합니다
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import sys

# AF_VSOCK = 40 (Linux 상수, Python socket 모듈에 없을 수 있음)
_AF_VSOCK = 40
_VMADDR_CID_ANY = 0xFFFFFFFF   # 모든 CID에서 연결 허용
_VSOCK_PORT = 52000

_HEADER_FMT = ">I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

# language → [인터프리터, 플래그] 매핑
_INTERPRETERS: dict[str, list[str]] = {
    "python":     ["python3", "-c"],
    "python3":    ["python3", "-c"],
    "javascript": ["node", "-e"],
    "js":         ["node", "-e"],
    "bash":       ["bash", "-c"],
    "sh":         ["sh", "-c"],
}


# ── 프레이밍 ──────────────────────────────────────────────────────────────────

async def _recv_json(reader: asyncio.StreamReader) -> dict:
    header = await asyncio.wait_for(reader.readexactly(_HEADER_SIZE), timeout=5.0)
    (length,) = struct.unpack(_HEADER_FMT, header)
    payload = await asyncio.wait_for(reader.readexactly(length), timeout=30.0)
    return json.loads(payload.decode("utf-8"))


async def _send_json(writer: asyncio.StreamWriter, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack(_HEADER_FMT, len(payload))
    writer.write(header + payload)
    await writer.drain()


# ── 코드 실행 ─────────────────────────────────────────────────────────────────

async def _execute(req: dict) -> dict:
    """
    요청에 따라 코드를 서브프로세스로 실행하고 결과를 반환합니다.

    Args:
        req: 실행 요청 딕셔너리

    Returns:
        {"stdout": str, "stderr": str, "exit_code": int}
    """
    language: str = req.get("language", "python").lower()
    code: str = req.get("code", "")
    stdin_data: str = req.get("stdin", "")
    timeout: int = int(req.get("timeout", 30))

    # 환경변수 병합 (현재 환경 + 요청 환경변수)
    env = {**os.environ}
    extra_env: dict = req.get("env", {})
    env.update(extra_env)

    interpreter = _INTERPRETERS.get(language, ["sh", "-c"])
    cmd = interpreter + [code]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdin_bytes = stdin_data.encode("utf-8") if stdin_data else None
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"stdout": "", "stderr": "실행 시간 초과", "exit_code": 124}

        return {
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode or 0,
        }

    except FileNotFoundError as exc:
        return {
            "stdout": "",
            "stderr": f"인터프리터를 찾을 수 없습니다: {exc}",
            "exit_code": 127,
        }
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "exit_code": -1}


# ── 연결 처리 ─────────────────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """단일 호스트 연결을 처리합니다."""
    peer = writer.get_extra_info("peername", "unknown")
    print(f"[GuestAgent] 연결: {peer}", flush=True)

    try:
        req = await _recv_json(reader)
        result = await _execute(req)
        await _send_json(writer, result)
    except asyncio.TimeoutError:
        try:
            await _send_json(writer, {
                "stdout": "", "stderr": "요청 수신 타임아웃", "exit_code": -1,
            })
        except Exception:
            pass
    except Exception as exc:
        print(f"[GuestAgent] 처리 오류: {exc}", flush=True)
        try:
            await _send_json(writer, {
                "stdout": "", "stderr": str(exc), "exit_code": -1,
            })
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ── 서버 진입점 ───────────────────────────────────────────────────────────────

async def main() -> None:
    """AF_VSOCK 서버를 시작하고 연결을 대기합니다."""
    # AF_VSOCK 소켓 생성
    # Python 3.7+에서 socket.AF_VSOCK(=40)을 직접 지원하지만
    # 일부 빌드에서 누락될 수 있으므로 raw 상수 사용
    sock = socket.socket(_AF_VSOCK, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((_VMADDR_CID_ANY, _VSOCK_PORT))
    sock.listen(16)
    sock.setblocking(False)

    server = await asyncio.start_server(_handle_connection, sock=sock)
    print(f"[GuestAgent] VSock 리스닝 시작: port={_VSOCK_PORT}", flush=True)
    sys.stdout.flush()

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
