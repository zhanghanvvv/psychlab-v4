"""PLUX biosignalsplux 设备封装。

负责：设备发现、蓝牙连接、传感器识别、数据采集控制。
当 PLUX 原生库不可用时自动回退到模拟设备模式。
"""

import sys
import time
import random
import math
import threading
import platform
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass

from ..constants import SENSOR_TYPES, SENSOR_NAMES_CN, CHANNEL_MASKS, MAX_SAMPLING_RATES, DEFAULT_RESOLUTION
from .sensor_types import get_sensor_meta
from ..utils.logger import logger


# ── PLUX API 路径解析 ──
_API_BASE_DIR = "PLUX-API-Python3"
_API_BASE_PATH = Path(__file__).resolve().parent.parent.parent / _API_BASE_DIR

_plux_available = False
_plux_error = ""

try:
    def _resolve_api_dir() -> str:
        """解析当前平台对应的 PLUX API 目录。"""
        system = platform.system()
        machine = platform.machine().lower()
        arch = platform.architecture()[0][:2]
        major, minor = int(platform.python_version_tuple()[0]), int(platform.python_version_tuple()[1])
        version_suffix = f"{major}{minor}"

        if system == "Windows":
            candidates = [f"Win{arch}_{version_suffix}"]
        elif system == "Darwin":
            if machine == "x86_64":
                candidates = [f"MacOS/Intel{version_suffix}", "MacOS"]
            else:
                candidates = [f"M1_{version_suffix}"]
        elif system == "Linux":
            if arch == "64":
                candidates = [f"Linux64_{version_suffix}", "Linux64"]
            else:
                candidates = [f"LinuxARM{arch}_{version_suffix}"]
        else:
            candidates = []

        for c in candidates:
            if (_API_BASE_PATH / c).is_dir():
                return c
        raise ValueError(
            f"PLUX API 目录未找到: system={system}, python={platform.python_version()}, "
            f"尝试={candidates}, 可用={[p.name for p in _API_BASE_PATH.iterdir() if p.is_dir()] if _API_BASE_PATH.is_dir() else 'none'}"
        )

    _api_dir = _resolve_api_dir()
    _api_path = _API_BASE_PATH / _api_dir
    sys.path.append(str(_api_path))
    import plux as _plux
    _plux_available = True
    logger.info(f"PLUX API 加载成功: {_api_path}")

except Exception as e:
    _plux_error = str(e)
    logger.warning(f"PLUX API 不可用（{_plux_error}），将使用模拟设备模式")


# ── 数据结构 ──
@dataclass
class SensorInfo:
    """已连接传感器信息。"""
    port: int                # 通道号 (1-8)
    sensor_type: str         # 传感器类型名 (如 "ECG")
    sensor_name_cn: str      # 中文名
    serial_num: str          # 序列号
    color: str               # 颜色标识


@dataclass
class DeviceInfo:
    """设备信息。"""
    address: str             # 蓝牙地址
    name: str = ""           # 设备名称
    channels: int = 0        # 通道数
    battery: int = 100       # 电池电量 %


# ── 真实 PLUX 设备 ──
if _plux_available:
    class _PluxDevice(_plux.SignalsDev):
        """PLUX 设备子类，实现 onRawFrame 回调。"""

        def __init__(self, address: str, on_frame: Callable = None):
            _plux.MemoryDev.__init__(address)
            self._address = address
            self._on_frame = on_frame
            self._should_stop = False
            self._n_seq = 0

        def onRawFrame(self, nSeq, data):
            """每帧数据回调。"""
            self._n_seq = nSeq
            if self._on_frame:
                self._on_frame(nSeq, list(data))
            return self._should_stop

        def request_stop(self):
            """请求停止采集（线程安全）。"""
            self._should_stop = True


# ── 模拟设备（无硬件时）──
class _MockDevice:
    """模拟设备，生成仿真的生理信号数据。"""

    def __init__(self, address: str, on_frame: Callable = None):
        self._address = address
        self._on_frame = on_frame
        self._should_stop = False
        self._n_seq = 0
        self._thread = None
        self._freq = 1000
        self._channels = 0x01
        self._resolution = 16
        # 信号生成参数
        self._t = 0.0
        self._phase = 0.0

    def _generate_signal(self, ch: int, t: float) -> float:
        """为每个通道生成仿真信号。"""
        # 根据通道号模拟不同信号
        if ch == 0:  # ECG
            # 心率约 72bpm = 1.2Hz
            beat = t * 1.2
            phase = beat - int(beat)
            if phase < 0.1:
                return 0.8 * (phase / 0.1) ** 2 * (1 - phase / 0.1)
            elif phase < 0.15:
                return -0.3
            else:
                return 0.0 + 0.05 * random.gauss(0, 1)
        elif ch == 1:  # EMG
            return random.gauss(0, 0.1) + 0.3 * sum(
                random.gauss(0, 1) for _ in range(5)
            ) / 5
        elif ch == 2:  # EDA
            return 5.0 + 3.0 * (1 + math.sin(t * 0.1)) / 2 + random.gauss(0, 0.05)
        elif ch == 3:  # RESP
            return 50.0 * math.sin(t * 0.25 * 2 * math.pi) + random.gauss(0, 0.5)
        elif ch == 4:  # SpO2
            return 97.0 + random.gauss(0, 0.3)
        else:
            return random.gauss(0, 0.1)

    def _run(self):
        """模拟采集线程。"""
        interval = 1.0 / self._freq
        n_channels = bin(self._channels).count("1")
        while not self._should_stop:
            data = []
            for ch in range(n_channels):
                data.append(self._generate_signal(ch, self._t))
            self._n_seq += 1
            if self._on_frame:
                self._on_frame(self._n_seq, data)
            self._t += interval
            time.sleep(interval)

    def getBattery(self) -> float:
        return 85.0

    def getSensors(self) -> dict:
        """返回模拟传感器列表（固定3通道: ECG/EMG/EDA）。"""
        # 模拟设备始终返回3个已连接传感器
        sensor_list = [
            (1, "ECG"), (2, "EMG"), (3, "EDA"),
        ]
        sensors = {}
        for port, stype in sensor_list:
            # 查找传感器类型枚举值
            clas = 0
            for k, v in SENSOR_TYPES.items():
                if v == stype:
                    clas = k
                    break
            sensors[port] = type("S", (), {
                "clas": clas,
                "serialNum": f"MOCK{port:03d}",
                "color": port,
            })()
        return sensors

    def start(self, freq: int, channels: int, resolution: int = 16):
        self._freq = freq
        self._channels = channels
        self._resolution = resolution
        self._should_stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def loop(self):
        """阻塞直到停止。"""
        if self._thread:
            self._thread.join()

    def stop(self):
        self._should_stop = True

    def close(self):
        pass

    def request_stop(self):
        self._should_stop = True


# ── 设备管理器 ──
class DeviceManager:
    """设备管理器：发现、连接、采集控制。"""

    def __init__(self):
        self._device = None
        self._on_frame_cb = None
        self._connected_sensors: list[SensorInfo] = []
        self._device_info: Optional[DeviceInfo] = None

    @property
    def is_mock(self) -> bool:
        """是否为模拟模式。"""
        return not _plux_available

    @property
    def is_connected(self) -> bool:
        """设备是否已连接。"""
        return self._device is not None

    def discover(self) -> list[str]:
        """扫描蓝牙设备，返回地址列表。"""
        if _plux_available:
            try:
                discoverer = _plux.PluxDeviceDiscoverer()
                discoverer.scan()
                time.sleep(5)
                devices = discoverer.getDevices()
                return [addr for addr, name in devices.items()]
            except Exception as e:
                logger.error(f"设备扫描失败: {e}")
                return []
        else:
            return ["MOCK:BTH00:07:80:4D:2E:76"]

    def connect(self, address: str) -> bool:
        """连接到指定地址的设备。"""
        try:
            if _plux_available:
                self._device = _PluxDevice(address, on_frame=self._on_frame_dispatch)
            else:
                self._device = _MockDevice(address, on_frame=self._on_frame_dispatch)

            battery = self._device.getBattery()
            self._device_info = DeviceInfo(
                address=address, battery=int(battery)
            )
            logger.info(f"设备已连接: {address}, 电池: {battery:.0f}%")
            return True
        except Exception as e:
            logger.error(f"连接失败: {e}")
            self._device = None
            return False

    def disconnect(self):
        """断开设备连接。"""
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
            self._connected_sensors.clear()
            self._device_info = None
            logger.info("设备已断开")

    def get_connected_sensors(self) -> list[SensorInfo]:
        """获取已连接的传感器列表。"""
        if not self._device:
            return []

        sensors = self._device.getSensors()
        self._connected_sensors.clear()

        for port, sensor in sensors.items():
            stype = SENSOR_TYPES.get(sensor.clas, "UNKNOWN")
            meta = get_sensor_meta(stype)
            self._connected_sensors.append(SensorInfo(
                port=port,
                sensor_type=stype,
                sensor_name_cn=meta.name_cn,
                serial_num=sensor.serialNum,
                color="",
            ))

        if self._device_info:
            self._device_info.channels = len(self._connected_sensors)

        return self._connected_sensors

    def get_channel_mask(self, n_channels: int) -> int:
        """获取通道数对应的掩码。"""
        return CHANNEL_MASKS.get(n_channels, 0xFF)

    def get_max_sampling_rate(self, n_channels: int) -> int:
        """获取指定通道数的最大采样率。"""
        return MAX_SAMPLING_RATES.get(n_channels, 1000)

    def set_on_frame_callback(self, callback: Callable[[int, list], None]):
        """设置原始数据帧回调。"""
        self._on_frame_cb = callback

    def _on_frame_dispatch(self, n_seq: int, data: list):
        """分发数据帧到回调。"""
        if self._on_frame_cb:
            self._on_frame_cb(n_seq, data)

    def start_acquisition(self, sampling_rate: int, channel_mask: int,
                          resolution: int = DEFAULT_RESOLUTION) -> bool:
        """开始采集。"""
        if not self._device:
            logger.error("无设备连接，无法开始采集")
            return False
        try:
            self._device.start(sampling_rate, channel_mask, resolution)
            logger.info(f"采集开始: {sampling_rate}Hz, 掩码=0x{channel_mask:02X}")
            return True
        except Exception as e:
            logger.error(f"采集启动失败: {e}")
            return False

    def run_loop(self):
        """阻塞运行采集循环（在工作线程中调用）。"""
        if self._device:
            self._device.loop()

    def stop_acquisition(self):
        """停止采集。"""
        if self._device:
            self._device.request_stop()
            time.sleep(0.1)
            try:
                self._device.stop()
            except Exception:
                pass
            logger.info("采集已停止")

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        return self._device_info

    @property
    def connected_sensors(self) -> list[SensorInfo]:
        return self._connected_sensors
