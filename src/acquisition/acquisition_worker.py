"""采集工作线程。

在 QThread 中运行 PLUX 设备采集循环，将数据推入 RingBuffer，
通过 Qt 信号通知主线程更新 GUI。支持连续采集模式（≥10h）。
"""

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QThread, Signal, QElapsedTimer

from ..device.plux_wrapper import DeviceManager, SensorInfo
from .ring_buffer import RingBuffer
from ..utils.logger import logger


class AcquisitionWorker(QThread):
    """采集工作线程。"""

    # ── Qt 信号 ──
    dataReady = Signal(int, list)         # nSeq, data (原始帧)
    sensorsDetected = Signal(list)         # 已连接传感器列表 [SensorInfo]
    batteryUpdated = Signal(int)          # 电池电量 %
    acquisitionStarted = Signal()         # 采集已启动
    acquisitionFinished = Signal()        # 采集已结束
    errorOccurred = Signal(str)           # 错误信息
    statusMessage = Signal(str)           # 状态消息

    def __init__(self, device_address: str, sampling_rate: int = 1000,
                 channel_mask: int = 0x01, duration: Optional[float] = None,
                 ring_buffer: Optional[RingBuffer] = None):
        """
        Args:
            device_address: 蓝牙设备地址
            sampling_rate: 采样率 (Hz)
            channel_mask: 通道掩码
            duration: 采集时长(秒)，None=连续模式(不自动停止)
            ring_buffer: 外部 RingBuffer，如不提供则内部创建
        """
        super().__init__()
        self._address = device_address
        self._sampling_rate = sampling_rate
        self._channel_mask = channel_mask
        self._duration = duration
        self._n_channels = bin(channel_mask).count("1")
        self._device_mgr = DeviceManager()
        self._ring_buffer = ring_buffer or RingBuffer(
            self._n_channels, sampling_rate * 30  # 30秒缓冲
        )
        self._elapsed = QElapsedTimer()
        self._frame_count = 0

    @property
    def ring_buffer(self) -> RingBuffer:
        return self._ring_buffer

    @property
    def device_manager(self) -> DeviceManager:
        return self._device_mgr

    def run(self):
        """线程主函数：连接设备 → 开始采集 → 阻塞循环 → 停止。"""
        try:
            # 1. 连接设备
            self.statusMessage.emit("正在连接设备...")
            if not self._device_mgr.connect(self._address):
                self.errorOccurred.emit("设备连接失败")
                return

            # 2. 查询电池和传感器
            battery = int(self._device_mgr.device_info.battery)
            self.batteryUpdated.emit(battery)

            sensors = self._device_mgr.get_connected_sensors()
            self.sensorsDetected.emit(sensors)

            # 3. 设置数据回调：写入 RingBuffer + 发送信号
            self._frame_count = 0

            def on_frame(n_seq, data):
                self._frame_count = n_seq
                self._ring_buffer.push_frame(data)
                self.dataReady.emit(n_seq, data)

            self._device_mgr.set_on_frame_callback(on_frame)

            # 4. 开始采集
            self.statusMessage.emit(f"开始采集: {self._sampling_rate}Hz, "
                                    f"{self._n_channels}通道")
            if not self._device_mgr.start_acquisition(
                self._sampling_rate, self._channel_mask
            ):
                self.errorOccurred.emit("采集启动失败")
                return

            self._elapsed.start()
            self.acquisitionStarted.emit()

            # 5. 阻塞运行采集循环
            self._device_mgr.run_loop()

            # 6. 停止采集
            self._device_mgr.stop_acquisition()
            self.acquisitionFinished.emit()
            self.statusMessage.emit(
                f"采集结束，共 {self._frame_count} 帧，"
                f"时长 {self._elapsed.elapsed() / 1000.0:.1f}s"
            )

        except Exception as e:
            logger.error(f"采集线程异常: {e}", exc_info=True)
            self.errorOccurred.emit(str(e))
        finally:
            if self._device_mgr.is_connected:
                self._device_mgr.disconnect()

    def stop(self):
        """请求停止采集（线程安全）。"""
        if self._device_mgr.is_connected:
            self._device_mgr.stop_acquisition()

    @property
    def elapsed_seconds(self) -> float:
        """已采集时长（秒）。"""
        return self._elapsed.elapsed() / 1000.0

    @property
    def frame_count(self) -> int:
        """已采集帧数。"""
        return self._frame_count
