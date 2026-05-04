"""
MarketplaceHandler — 외부 마켓플레이스 에이전트 설치 관리자
- 외부 URL/ID로부터 에이전트 명세(Manifest)를 가져옵니다.
- AgentBuilderHandler를 사용하여 에이전트를 빌드합니다.
- 빌드 완료 후 AgentRegistry(인메모리)와 HealthMonitor(Redis)에 에이전트를 등록합니다.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from .agent_builder_handler import AgentBuilderHandler
from .registry import AgentRegistry

if TYPE_CHECKING:
    from .health_monitor import HealthMonitor

logger = logging.getLogger("cassiopeia_agent.marketplace_handler")

# 허용되는 에이전트 이름 패턴: 알파벳·숫자·언더스코어, 최대 64자
_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
# 허용되는 패키지 이름 패턴: PyPI 사양 (패키지명, 버전 스펙 포함)
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]+([><=!~^]{1,2}[A-Za-z0-9_\-\.\*]+)?$")
_MAX_CODE_BYTES = 512 * 1024  # 512 KB
_MAX_PACKAGES = 20
_VALID_PERMISSION_PRESETS = frozenset({"minimal", "standard", "trusted"})


def _validate_manifest(manifest: dict[str, Any]) -> None:
    """마켓플레이스 매니페스트 입력값을 서버사이드에서 검증한다.

    유효하지 않은 값이 있으면 ValueError 를 발생시킨다.
    """
    # name 검증
    name = str(manifest.get("name", "")).strip()
    if not name:
        raise ValueError("매니페스트 name 필드가 비어 있습니다.")
    if not _AGENT_NAME_RE.match(name):
        raise ValueError(
            f"매니페스트 name 은 영문·숫자·언더스코어 1~64자여야 합니다: {name!r}"
        )

    # code 검증
    code = str(manifest.get("code", "")).strip()
    if not code:
        raise ValueError("매니페스트 code 필드가 비어 있습니다.")
    if len(code.encode("utf-8")) > _MAX_CODE_BYTES:
        raise ValueError(
            f"매니페스트 code 크기가 허용 한도({_MAX_CODE_BYTES // 1024} KB)를 초과합니다."
        )

    # packages 검증
    packages: list[Any] = manifest.get("packages") or []
    if len(packages) > _MAX_PACKAGES:
        raise ValueError(
            f"packages 목록은 최대 {_MAX_PACKAGES}개까지 허용됩니다. (현재: {len(packages)})"
        )
    for pkg in packages:
        pkg_str = str(pkg).strip()
        if not _PACKAGE_NAME_RE.match(pkg_str):
            raise ValueError(
                f"packages 항목에 허용되지 않은 문자가 포함되어 있습니다: {pkg_str!r}"
            )

    # permissions 검증 (선택 필드)
    permissions = manifest.get("permissions")
    if permissions is not None and permissions not in _VALID_PERMISSION_PRESETS:
        raise ValueError(
            f"permissions 은 {sorted(_VALID_PERMISSION_PRESETS)} 중 하나여야 합니다: {permissions!r}"
        )


def _validate_marketplace_url(url: str) -> tuple[str, str, str]:
    """
    SSRF 방어: 내부망·루프백·링크로컬 주소로의 요청을 차단합니다.
    허용 스킴: https, http (내부 IP 아닌 경우에 한함)
    반환: (resolved_ip, original_hostname, modified_url_with_ip)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"허용되지 않은 URL 스킴: '{parsed.scheme}'. https 또는 http만 허용됩니다.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL에 호스트가 없습니다.")

    # DNS 해석 후 실제 IP로 검사 (DNS rebinding 방어)
    try:
        resolved_ip = socket.gethostbyname(hostname)
    except socket.gaierror as e:
        raise ValueError(f"호스트를 해석할 수 없습니다: {hostname} — {e}")

    addr = ipaddress.ip_address(resolved_ip)
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        raise ValueError(
            f"내부 또는 예약된 IP 주소로의 요청은 허용되지 않습니다: {resolved_ip}"
        )
        
    # DNS Rebinding 방어를 위해 IP 주소 기반 URL 생성
    # Host 헤더는 원본 호스트 유지 필요
    netloc = resolved_ip
    if parsed.port:
        netloc = f"{resolved_ip}:{parsed.port}"
        
    modified_url = parsed._replace(netloc=netloc).geturl()
    return resolved_ip, hostname, modified_url


class MarketplaceHandler:
    def __init__(
        self,
        builder_handler: AgentBuilderHandler,
        registry: AgentRegistry,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        self.builder = builder_handler
        self.registry = registry
        self.health_monitor = health_monitor

    async def install_from_marketplace(self, item_url: str, task_id: str) -> dict[str, Any]:
        """
        외부 마켓플레이스 URL에서 에이전트 정보를 가져와 설치 및 등록합니다.

        매니페스트 필수/선택 필드:
          name         (str, 필수)   — 에이전트 이름 (예: "weather")
          code         (str, 필수)   — user_code.py 소스 문자열
          language     (str)         — "python" | "javascript" (기본값: "python")
          description  (str)         — 에이전트 설명
          packages     (list[str])   — 설치할 패키지 목록
          port         (int)         — FastAPI 서버 포트 (기본값: 8010)
          permissions  (str)         — "minimal" | "standard" | "trusted" (기본값: "standard")
          lifecycle_type (str)       — "long_running" | "ephemeral" (기본값: "long_running")
          capabilities (list[str])   — NLU 라우팅용 액션 목록
          nlu_description (str)      — NLU 동적 캐퍼빌리티 설명 (동적 라우팅용)
        """
        logger.info("[Marketplace] 설치 시도: %s", item_url)

        try:
            # 1. SSRF 방어: 내부망 URL 차단 및 DNS Rebinding 방어를 위해 IP 확인
            resolved_ip, original_hostname, safe_url = _validate_marketplace_url(item_url)

            # 2. 마켓플레이스로부터 매니페스트(명세) 가져오기 (IP 주소 사용 및 Host 헤더 전달)
            headers = {"Host": original_hostname}
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                resp = await client.get(safe_url, headers=headers)
                resp.raise_for_status()
                manifest: dict[str, Any] = resp.json()

            # 3. 매니페스트 입력값 검증 (이름 패턴, 코드 크기, 패키지 안전성)
            _validate_manifest(manifest)
            agent_name = manifest["name"].strip()

            # 4. 에이전트 빌드 실행
            build_result = await self.builder.build_agent(manifest, task_id)

            if build_result.get("status") == "FAILED":
                return build_result

            # 5. 레지스트리 등록 — 인메모리(AgentRegistry) + Redis(HealthMonitor)
            registered_name = f"{agent_name}_agent"
            capability_desc = manifest.get("description", f"{agent_name} 에이전트")
            capabilities: list[str] = manifest.get("capabilities") or []
            lifecycle_type: str = manifest.get("lifecycle_type", "long_running")
            nlu_description: str = manifest.get("nlu_description", "")

            self.registry.register_agent(registered_name, capability_desc)

            if self.health_monitor is not None:
                await self.health_monitor.register_agent(
                    registered_name,
                    capabilities,
                    lifecycle_type=lifecycle_type,
                    nlu_description=nlu_description,
                )

            logger.info("[Marketplace] 설치 및 등록 성공: %s", registered_name)

            return {
                "status": "COMPLETED",
                "task_id": task_id,
                "result_data": {
                    "summary": f"마켓플레이스로부터 '{registered_name}' 에이전트 설치 및 등록이 완료되었습니다.",
                    "details": build_result.get("result_data"),
                },
            }

        except Exception as exc:
            logger.error("[Marketplace] 설치 중 오류 발생: %s", exc)
            return {
                "status": "FAILED",
                "task_id": task_id,
                "result_data": {},
                "error": {"code": "MARKETPLACE_INSTALL_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }
