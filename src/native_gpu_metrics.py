# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
"""直接调用 NVIDIA NVML/NVAPI 的 GPU 指标采集。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from typing import Callable


LOGGER = logging.getLogger(__name__)
NVML_SUCCESS = 0
NVML_TEMPERATURE_GPU = 0
NVML_CLOCK_GRAPHICS = 0
NVAPI_OK = 0
NVAPI_MAX_PHYSICAL_GPUS = 64
NVAPI_MAX_GPU_UTILIZATIONS = 8


class GpuMetricsError(OSError):
    """原生 GPU 驱动接口不可用。"""


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class _NvUtilizationDomain(ctypes.Structure):
    _fields_ = [("present", wintypes.BOOL), ("percentage", ctypes.c_int)]


class _NvDynamicPstatesInfoEx(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("domains", _NvUtilizationDomain * NVAPI_MAX_GPU_UTILIZATIONS),
    ]


class _NvApiUtilization:
    """只绑定 AirPerf 使用的 NVAPI 动态 P-State 利用率接口。"""

    _INITIALIZE_ID = 0x0150E828
    _ENUM_PHYSICAL_GPUS_ID = 0xE5AC921F
    _GET_DYNAMIC_PSTATES_INFO_EX_ID = 0x60DED2ED

    def __init__(self, loader: Callable[..., object] = ctypes.WinDLL) -> None:
        library = loader("nvapi64.dll", use_last_error=True)
        query = library.nvapi_QueryInterface
        query.argtypes = [ctypes.c_uint]
        query.restype = ctypes.c_void_p

        initialize_pointer = query(self._INITIALIZE_ID)
        enum_pointer = query(self._ENUM_PHYSICAL_GPUS_ID)
        utilization_pointer = query(self._GET_DYNAMIC_PSTATES_INFO_EX_ID)
        if not initialize_pointer or not enum_pointer or not utilization_pointer:
            raise GpuMetricsError("NVAPI 缺少动态 P-State 接口")

        initialize = ctypes.CFUNCTYPE(ctypes.c_int)(initialize_pointer)
        enum_gpus = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_int),
        )(enum_pointer)
        self._get_utilization = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(_NvDynamicPstatesInfoEx),
        )(utilization_pointer)

        if initialize() != NVAPI_OK:
            raise GpuMetricsError("NVAPI 初始化失败")
        handles = (ctypes.c_void_p * NVAPI_MAX_PHYSICAL_GPUS)()
        count = ctypes.c_int()
        if enum_gpus(handles, ctypes.byref(count)) != NVAPI_OK or count.value < 1:
            raise GpuMetricsError("NVAPI 未找到 NVIDIA GPU")
        self._handle = handles[0]

    def sample(self) -> dict[str, float]:
        state = _NvDynamicPstatesInfoEx()
        state.version = ctypes.sizeof(state) | (1 << 16)
        if self._get_utilization(self._handle, ctypes.byref(state)) != NVAPI_OK:
            return {}
        names = (
            "gpuUsagePercent",
            "gpuFrameBufferPercent",
            "gpuVideoEnginePercent",
            "gpuBusPercent",
        )
        result: dict[str, float] = {}
        for index, name in enumerate(names):
            domain = state.domains[index]
            if domain.present:
                result[name] = float(domain.percentage)
        return result


class NvidiaGpuMetrics:
    """直接读取系统 NVIDIA 驱动，不加载 AirPerf/OpenHardwareMonitor。"""

    def __init__(self, loader: Callable[..., object] = ctypes.WinDLL) -> None:
        if os.name != "nt":
            raise GpuMetricsError("NVIDIA 原生指标仅支持 Windows")
        self._loader = loader
        self._nvml: object | None = None
        self._device = ctypes.c_void_p()
        self._nvapi: _NvApiUtilization | None = None
        self._owns_nvml = False

    def open(self) -> None:
        try:
            nvml = self._loader("nvml.dll", use_last_error=True)
        except OSError as error:
            raise GpuMetricsError("系统未提供 NVIDIA NVML") from error
        self._configure_nvml(nvml)
        if nvml.nvmlInit_v2() != NVML_SUCCESS:
            raise GpuMetricsError("NVML 初始化失败")
        self._owns_nvml = True
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self._device)) != NVML_SUCCESS:
            self.close()
            raise GpuMetricsError("NVML 未找到 NVIDIA GPU")
        self._nvml = nvml
        try:
            self._nvapi = _NvApiUtilization(self._loader)
        except (AttributeError, GpuMetricsError, OSError) as error:
            LOGGER.info("NVAPI 细分 GPU 利用率不可用：%s", error)

    @staticmethod
    def _configure_nvml(nvml: object) -> None:
        nvml.nvmlInit_v2.argtypes = []
        nvml.nvmlInit_v2.restype = ctypes.c_int
        nvml.nvmlShutdown.argtypes = []
        nvml.nvmlShutdown.restype = ctypes.c_int
        nvml.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        nvml.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        nvml.nvmlDeviceGetTemperature.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        nvml.nvmlDeviceGetTemperature.restype = ctypes.c_int
        nvml.nvmlDeviceGetClockInfo.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        nvml.nvmlDeviceGetClockInfo.restype = ctypes.c_int
        nvml.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlUtilization)]
        nvml.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
        nvml.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
        nvml.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        if hasattr(nvml, "nvmlDeviceGetDecoderUtilization"):
            nvml.nvmlDeviceGetDecoderUtilization.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint),
            ]
            nvml.nvmlDeviceGetDecoderUtilization.restype = ctypes.c_int

    def sample(self) -> dict[str, float]:
        if self._nvml is None:
            raise GpuMetricsError("NVML 会话尚未打开")
        result: dict[str, float] = {}
        self._read_uint("gpuTemperatureC", "nvmlDeviceGetTemperature", result, NVML_TEMPERATURE_GPU)
        self._read_uint("gpuFrequencyMhz", "nvmlDeviceGetClockInfo", result, NVML_CLOCK_GRAPHICS)

        utilization = _NvmlUtilization()
        if self._nvml.nvmlDeviceGetUtilizationRates(self._device, ctypes.byref(utilization)) == NVML_SUCCESS:
            result["gpuUsagePercent"] = float(utilization.gpu)
            result["gpuFrameBufferPercent"] = float(utilization.memory)

        memory = _NvmlMemory()
        if self._nvml.nvmlDeviceGetMemoryInfo(self._device, ctypes.byref(memory)) == NVML_SUCCESS:
            result["gpuMemoryUsedMb"] = round(memory.used / 1_048_576, 4)

        decoder = getattr(self._nvml, "nvmlDeviceGetDecoderUtilization", None)
        if decoder is not None:
            percent = ctypes.c_uint()
            period = ctypes.c_uint()
            if decoder(self._device, ctypes.byref(percent), ctypes.byref(period)) == NVML_SUCCESS:
                result["gpuVideoEnginePercent"] = float(percent.value)

        if self._nvapi is not None:
            result.update(self._nvapi.sample())
        return result

    def _read_uint(self, key: str, function_name: str, result: dict[str, float], argument: int) -> None:
        value = ctypes.c_uint()
        function = getattr(self._nvml, function_name)
        if function(self._device, argument, ctypes.byref(value)) == NVML_SUCCESS:
            result[key] = float(value.value)

    def close(self) -> None:
        self._nvapi = None
        if self._nvml is not None and self._owns_nvml:
            status = self._nvml.nvmlShutdown()
            if status != NVML_SUCCESS:
                LOGGER.debug("NVML 关闭返回状态 %s", status)
        self._nvml = None
        self._device = ctypes.c_void_p()
        self._owns_nvml = False


__all__ = ["GpuMetricsError", "NvidiaGpuMetrics"]
