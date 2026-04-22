"""
ContainerPermissions — 에이전트 컨테이너 별 권한 설정 모델

에이전트 빌드 시 권한을 지정하면:
  1. 생성된 Dockerfile에 비루트 사용자 설정이 추가됩니다.
  2. docker-compose 스니펫에 security_opt, cap_drop, network,
     read_only, 리소스 제한 등이 추가됩니다.

프리셋:
  minimal  — 네트워크 차단 · 읽기 전용 · 256MB  (계산/코드 실행 에이전트)
  standard — 내부 네트워크 · 읽기 전용 · 512MB  (기본값, 일반 에이전트)
  trusted  — 전체 네트워크 · 읽기/쓰기 · 1GB · LLM 접근 허용  (파일·외부 API·LLM 접근 에이전트)

사용 예시:
    from tools.agent_builder import AgentBuilder
    from tools.agent_builder.permissions import ContainerPermissions

    # 프리셋 사용
    perms = ContainerPermissions.minimal()

    # 세부 조정
    perms = ContainerPermissions(
        network="full",
        filesystem="readwrite",
        memory_mb=1024,
        extra_capabilities=["NET_BIND_SERVICE"],
        allow_llm_access=True,
    )

    # LLM 접근만 활성화 (외부 API 키 환경변수 자동 주입)
    perms = ContainerPermissions(network="full", allow_llm_access=True)

    builder = AgentBuilder()
    builder.build(..., permissions=perms)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type NetworkMode = Literal["none", "internal", "full"]
type FilesystemMode = Literal["readonly", "readwrite"]
type PermissionPreset = Literal["minimal", "standard", "trusted"]


@dataclass
class ContainerPermissions:
    """
    컨테이너 별 권한 설정.

    Attributes:
        network:             네트워크 접근 모드
                               "none"     — 완전 차단 (외부·내부 모두 불가)
                               "internal" — Docker 내부 네트워크만 허용 (기본값)
                               "full"     — 외부 인터넷 접근 허용
        filesystem:          파일시스템 접근 모드
                               "readonly"  — 루트 FS 읽기 전용, writable_paths만 tmpfs
                               "readwrite" — 쓰기 허용 (파일·빌드 에이전트 등)
        writable_paths:      readonly 모드에서 tmpfs로 마운트할 쓰기 가능 경로
        memory_mb:           메모리 상한 (MB)
        cpu_limit:           CPU 상한 (코어 수, 소수점 허용)
        pids_limit:          컨테이너 내 최대 프로세스(PID) 수
        extra_capabilities:  ALL DROP 이후 추가로 허용할 Linux Capability 목록
                               예: ["NET_BIND_SERVICE", "CHOWN"]
        run_as_nonroot:      비루트 사용자(appuser)로 실행 여부 (기본 True)
        no_new_privileges:   프로세스 권한 상승(setuid 등) 차단 여부 (기본 True)
        allow_llm_access:    LLM API 접근 허용 여부.
                               True이면 llm_env_vars 환경변수를 컨테이너에 주입합니다.
                               network="none"인 경우 LLM API에 도달할 수 없으므로
                               allow_llm_access=True와 network="none"을 동시에 설정하면
                               ValueError가 발생합니다.
        llm_env_vars:        allow_llm_access=True 시 컨테이너에 주입할 환경변수 목록.
                               기본값: ANTHROPIC_API_KEY, GEMINI_API_KEY,
                                        LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, LOCAL_LLM_API_KEY
    """

    # 네트워크
    network: NetworkMode = "internal"

    # 파일시스템
    filesystem: FilesystemMode = "readonly"
    writable_paths: list[str] = field(default_factory=lambda: ["/tmp"])

    # 리소스 제한
    memory_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 100

    # Linux Capabilities (항상 ALL DROP 후 아래만 추가)
    extra_capabilities: list[str] = field(default_factory=list)

    # 프로세스 컨텍스트
    run_as_nonroot: bool = True
    no_new_privileges: bool = True

    # LLM 접근
    allow_llm_access: bool = False
    llm_env_vars: list[str] = field(default_factory=lambda: [
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_MODEL",
        "LOCAL_LLM_API_KEY",
    ])

    def __post_init__(self) -> None:
        if self.allow_llm_access and self.network == "none":
            raise ValueError(
                "allow_llm_access=True이지만 network='none'으로 LLM API에 도달할 수 없습니다. "
                "network='internal'(로컬 LLM) 또는 network='full'(외부 API)로 변경하세요."
            )

    # ── 프리셋 팩토리 ─────────────────────────────────────────────────────────

    @classmethod
    def minimal(cls) -> ContainerPermissions:
        """
        최소 권한 — 네트워크 완전 차단, 읽기 전용 FS, 256MB.
        코드 실행·계산 전용 에이전트에 적합합니다.
        """
        return cls(
            network="none",
            filesystem="readonly",
            memory_mb=256,
            cpu_limit=0.5,
            pids_limit=64,
        )

    @classmethod
    def standard(cls) -> ContainerPermissions:
        """
        표준 권한 — 내부 네트워크, 읽기 전용 FS, 512MB. (기본값)
        Redis·OrchestraManager 통신이 필요한 일반 에이전트에 적합합니다.
        """
        return cls()  # 모든 필드가 기본값

    @classmethod
    def trusted(cls) -> ContainerPermissions:
        """
        신뢰 권한 — 전체 네트워크, 읽기/쓰기 FS, 1GB, LLM 접근 허용.
        외부 API 호출·파일 쓰기·LLM 사용이 필요한 에이전트에 적합합니다.
        """
        return cls(
            network="full",
            filesystem="readwrite",
            memory_mb=1024,
            cpu_limit=2.0,
            pids_limit=200,
            allow_llm_access=True,
        )

    @classmethod
    def from_preset(cls, preset: PermissionPreset) -> ContainerPermissions:
        """프리셋 이름으로 ContainerPermissions를 생성합니다."""
        match preset:
            case "minimal":
                return cls.minimal()
            case "trusted":
                return cls.trusted()
            case _:
                return cls.standard()

    # ── Dockerfile 렌더링 ──────────────────────────────────────────────────────

    def dockerfile_user_setup(self) -> str:
        """
        Dockerfile CMD 직전에 삽입할 사용자 설정 스니펫을 반환합니다.

        run_as_nonroot=True (기본)이면 비루트 appuser를 생성하고 /app 소유권을 변경합니다.
        """
        if not self.run_as_nonroot:
            return "# (루트 사용자로 실행 — run_as_nonroot=False 설정됨)\n"

        return (
            "# 보안: 비루트 사용자로 실행\n"
            "RUN addgroup -S appgroup \\\n"
            "    && adduser -S appuser -G appgroup \\\n"
            "    && chown -R appuser:appgroup /app\n"
            "USER appuser\n"
        )

    # ── docker-compose 렌더링 ──────────────────────────────────────────────────

    def to_compose_yaml(self) -> str:
        """
        docker-compose 서비스 블록에 추가할 보안·리소스 YAML 스니펫을 반환합니다.

        반환 문자열은 이미 4-space 들여쓰기가 적용되어 있어
        compose 서비스 블록 내부에 바로 붙여넣을 수 있습니다.
        """
        lines: list[str] = ["    # ── 컨테이너 권한 설정 (agent-builder 자동 생성) ──"]

        # security_opt
        lines.append("    security_opt:")
        if self.no_new_privileges:
            lines.append("      - no-new-privileges:true")

        # Linux Capabilities
        lines.append("    cap_drop:")
        lines.append("      - ALL")
        if self.extra_capabilities:
            lines.append("    cap_add:")
            for cap in sorted(self.extra_capabilities):
                lines.append(f"      - {cap}")

        # 파일시스템
        if self.filesystem == "readonly":
            lines.append("    read_only: true")
            if self.writable_paths:
                lines.append("    tmpfs:")
                for path in self.writable_paths:
                    size = 64
                    lines.append(f"      - {path}:size={size}m,mode=1777")

        # 리소스 제한
        lines.append(f"    mem_limit: {self.memory_mb}m")
        lines.append(f"    mem_reservation: {max(64, self.memory_mb // 4)}m")
        lines.append(f"    cpus: {self.cpu_limit:.1f}")
        lines.append(f"    pids_limit: {self.pids_limit}")

        # 네트워크
        if self.network == "none":
            lines.append('    network_mode: "none"')
        elif self.network == "internal":
            lines.append("    networks:")
            lines.append("      - agent_net")
        # "full" → Docker 기본 네트워크, 별도 설정 불필요

        # LLM 접근 환경변수
        if self.allow_llm_access and self.llm_env_vars:
            lines.append("    # LLM API 키 - 호스트 환경변수에서 주입 (미설정 시 빈 문자열)")
            lines.append("    environment:")
            for var in self.llm_env_vars:
                lines.append(f"      - {var}=${{{var}:-}}")

        return "\n".join(lines)

    # ── 사람이 읽을 수 있는 요약 ───────────────────────────────────────────────

    def summary(self) -> str:
        """권한 설정 요약을 반환합니다."""
        net_desc = {
            "none":     "차단 (인터넷·내부 모두 불가)",
            "internal": "내부 전용 (에이전트 간 통신만 가능)",
            "full":     "허용 (외부 인터넷 접근 가능)",
        }[self.network]

        fs_paths = ", ".join(self.writable_paths) if self.writable_paths else "없음"
        fs_desc = {
            "readonly":  f"읽기 전용 (tmpfs 쓰기 허용: {fs_paths})",
            "readwrite": "읽기/쓰기",
        }[self.filesystem]

        caps = ", ".join(self.extra_capabilities) if self.extra_capabilities else "없음"

        if self.allow_llm_access:
            llm_vars = ", ".join(self.llm_env_vars) if self.llm_env_vars else "없음"
            llm_desc = f"허용 (주입 변수: {llm_vars})"
        else:
            llm_desc = "차단"

        return "\n".join([
            f"  네트워크  : {net_desc}",
            f"  파일시스템: {fs_desc}",
            f"  메모리    : {self.memory_mb}MB",
            f"  CPU       : {self.cpu_limit}코어",
            f"  최대 PID  : {self.pids_limit}개",
            f"  비루트 실행: {'예' if self.run_as_nonroot else '아니오 (주의)'}",
            f"  추가 Capability: {caps}",
            f"  LLM 접근  : {llm_desc}",
        ])

    def preset_name(self) -> str:
        """현재 설정과 가장 가까운 프리셋 이름을 반환합니다."""
        if self == ContainerPermissions.minimal():
            return "minimal"
        if self == ContainerPermissions.trusted():
            return "trusted"
        return "standard (사용자 정의 포함)"
