import pytest
from unittest.mock import patch

from shared_core.llm.gemma_inference import (
    detect_hardware,
    get_gemma_inference_options,
    HardwareType,
    OSPlatform,
)


class TestHardwareDetection:
    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="arm64")
    def test_detects_apple_silicon_on_mac(self, mock_machine, mock_system):
        assert detect_hardware() == (OSPlatform.MACOS, HardwareType.APPLE_SILICON)

    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="x86_64")
    def test_detects_intel_mac_as_cpu(self, mock_machine, mock_system):
        assert detect_hardware() == (OSPlatform.MACOS, HardwareType.CPU)

    @patch("platform.system", return_value="Windows")
    @patch("shutil.which", return_value="nvidia-smi")
    def test_detects_nvidia_gpu_on_windows_with_smi(self, mock_which, mock_system):
        assert detect_hardware() == (OSPlatform.WINDOWS, HardwareType.NVIDIA_GPU)

    @patch("platform.system", return_value="Linux")
    @patch("shutil.which", return_value=None)
    def test_detects_cpu_on_linux_without_smi(self, mock_which, mock_system):
        assert detect_hardware() == (OSPlatform.LINUX, HardwareType.CPU)


class TestGemmaInferenceOptions:
    def test_gemma_options_for_apple_silicon(self):
        options = get_gemma_inference_options(OSPlatform.MACOS, HardwareType.APPLE_SILICON)
        # Apple Silicon (MPS): Full offload, no need to restrict threads strictly but typically > 4
        assert options["num_gpu"] == -1
        assert options["use_mmap"] is True
        assert options["num_thread"] >= 4

    def test_gemma_options_for_nvidia_gpu(self):
        options = get_gemma_inference_options(OSPlatform.LINUX, HardwareType.NVIDIA_GPU)
        # NVIDIA GPU: Full offload
        assert options["num_gpu"] == -1
        assert options["use_mmap"] is True

    def test_gemma_options_for_cpu(self):
        options = get_gemma_inference_options(OSPlatform.WINDOWS, HardwareType.CPU)
        # CPU only: No GPU offloading, rely on multiple threads
        assert options["num_gpu"] == 0
        assert options.get("num_thread", 0) > 0  # Should define thread count for CPU
