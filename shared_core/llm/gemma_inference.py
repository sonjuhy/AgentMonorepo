import platform
import shutil
from enum import Enum
from typing import Any, Dict


class OSPlatform(Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


class HardwareType(Enum):
    CPU = "cpu"
    NVIDIA_GPU = "nvidia_gpu"
    APPLE_SILICON = "apple_silicon"


def detect_hardware() -> tuple[OSPlatform, HardwareType]:
    """
    Detects the current OS and Hardware environment for optimized inference.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        os_platform = OSPlatform.MACOS
        if machine == "arm64":
            return os_platform, HardwareType.APPLE_SILICON
        return os_platform, HardwareType.CPU
    elif system == "windows":
        os_platform = OSPlatform.WINDOWS
    elif system == "linux":
        os_platform = OSPlatform.LINUX
    else:
        os_platform = OSPlatform.UNKNOWN

    # For Linux and Windows, check for nvidia-smi as a heuristic for NVIDIA GPU
    if shutil.which("nvidia-smi") is not None:
        return os_platform, HardwareType.NVIDIA_GPU

    return os_platform, HardwareType.CPU


def get_gemma_inference_options(
    os_platform: OSPlatform, hardware_type: HardwareType
) -> Dict[str, Any]:
    """
    Returns optimal generation options (e.g., for Ollama payload) for gemma-4-e4b
    based on the detected hardware and OS.
    """
    options: Dict[str, Any] = {
        "use_mmap": True,
    }

    if hardware_type == HardwareType.APPLE_SILICON:
        # Mac Silicon (M-series MPS)
        # Offload fully (-1) and optimize thread count
        options["num_gpu"] = -1
        options["num_thread"] = 8
    elif hardware_type == HardwareType.NVIDIA_GPU:
        # NVIDIA GPU
        # Offload fully to GPU
        options["num_gpu"] = -1
    elif hardware_type == HardwareType.CPU:
        # CPU Only
        # Disable GPU offloading, set reasonable thread count
        options["num_gpu"] = 0
        options["num_thread"] = 4

    return options
