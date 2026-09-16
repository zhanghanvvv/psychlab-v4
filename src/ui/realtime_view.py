"""实时波形显示界面。

使用 pyqtgraph 实现多通道实时滚动波形，支持事件标记显示。
"""

import numpy as np
from typing import Optional
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt, QPointF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QDoubleSpinBox

from ..acquisition.ring_buffer import RingBuffer
from ..constants import CHANNEL_COLORS
from ..device.sensor_types import get_sensor_meta
from ..utils.logger import logger


class RealtimeView(QWidget):
    """实时波形显示面板。"""

    def __init__(self, ring_buffer: Optional[RingBuffer] = None,
                 sampling_rate: int = 1000):
        super().__init__()
        self._ring_buffer = ring_buffer
        self._sampling_rate = sampling_rate
        self._n_channels = ring_buffer.n_channels if ring_buffer else 1
        self._plots = []
        self._curves = []
        self._event_lines = []  # 事件标记线列表
        self._sensor_labels = []
        self._time_window = 10  # 显示窗口(秒)
        self._refresh_interval = 50  # 刷新间隔(ms)

        self._init_ui()
        self._init_timer()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("时间窗(秒):"))

        self._window_combo = QComboBox()
        for sec in [5, 10, 30, 60]:
            self._window_combo.addItem(str(sec), sec)
        self._window_combo.currentIndexChanged.connect(self._on_window_changed)
        toolbar.addWidget(self._window_combo)

        toolbar.addStretch()

        self._auto_scale_btn = QPushButton("自动量程")
        self._auto_scale_btn.setCheckable(True)
        self._auto_scale_btn.setChecked(True)
        toolbar.addWidget(self._auto_scale_btn)

        layout.addLayout(toolbar)

        # 绘图区
        self._plot_widget = pg.GraphicsLayoutWidget()
        self._plot_widget.setBackground("k")  # 黑色背景
        layout.addWidget(self._plot_widget)

        self.setLayout(layout)

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_plots)
        self._timer.start(self._refresh_interval)

    def set_ring_buffer(self, ring_buffer: RingBuffer):
        """设置数据源。"""
        self._ring_buffer = ring_buffer
        self._n_channels = ring_buffer.n_channels
        self._setup_plots()

    def set_sensor_labels(self, sensor_labels: list[str]):
        """设置传感器标签（如 ['ECG', 'EMG', 'EDA']）。"""
        self._sensor_labels = sensor_labels
        self._setup_plots()

    def _setup_plots(self):
        """创建/重建子图。"""
        self._plot_widget.clear()
        self._plots.clear()
        self._curves.clear()
        self._event_lines.clear()

        for i in range(self._n_channels):
            # 创建子图
            plot = self._plot_widget.addPlot(row=i, col=0)
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel("left",
                           self._sensor_labels[i] if i < len(self._sensor_labels) else f"CH{i+1}")

            # 堆叠子图：除最后一个通道外，隐藏底部时间轴
            if i < self._n_channels - 1:
                plot.hideAxis("bottom")

            # Y 轴范围
            meta = get_sensor_meta(
                self._sensor_labels[i] if i < len(self._sensor_labels) else "UNKNOWN"
            )
            if meta.y_range:
                plot.setYRange(*meta.y_range)

            # 曲线
            color = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
            curve = plot.plot(pen=pg.mkPen(color, width=1.5))
            self._curves.append(curve)
            self._plots.append(plot)

    def _refresh_plots(self):
        """定时刷新波形。"""
        if not self._ring_buffer or not self._curves:
            return

        n_samples = int(self._time_window * self._sampling_rate)
        data = self._ring_buffer.read_latest(n_samples)

        if data.shape[0] == 0:
            return

        time_axis = np.linspace(
            -data.shape[0] / self._sampling_rate, 0, data.shape[0]
        )

        for i, curve in enumerate(self._curves):
            if i < data.shape[1]:
                curve.setData(time_axis, data[:, i])

                if self._auto_scale_btn.isChecked():
                    y_data = data[:, i]
                    y_min, y_max = np.min(y_data), np.max(y_data)
                    margin = max(abs(y_min), abs(y_max)) * 0.1 + 0.01
                    self._plots[i].setYRange(y_min - margin, y_max + margin)

    def _on_window_changed(self, index):
        self._time_window = self._window_combo.currentData()

    def add_event_marker(self, time_offset: float, description: str):
        """添加事件标记线。"""
        for plot in self._plots:
            line = pg.InfiniteLine(
                pos=time_offset, angle=90,
                pen=pg.mkPen("y", width=2, style=Qt.DashLine),
                label=description, labelPosition=0.9,
            )
            plot.addItem(line)
            self._event_lines.append(line)

        # 清理旧标记（只保留窗口内的）
        if len(self._event_lines) > 50:
            for line in self._event_lines[:len(self._event_lines) - 50]:
                for plot in self._plots:
                    try:
                        plot.removeItem(line)
                    except Exception:
                        pass
            self._event_lines = self._event_lines[-50:]

    def clear_event_markers(self):
        """清除所有事件标记。"""
        for line in self._event_lines:
            for plot in self._plots:
                try:
                    plot.removeItem(line)
                except Exception:
                    pass
        self._event_lines.clear()

    def stop(self):
        """停止刷新。"""
        self._timer.stop()

    def start(self):
        """开始刷新。"""
        self._timer.start(self._refresh_interval)

    def set_sampling_rate(self, rate: int):
        """更新采样率。"""
        self._sampling_rate = rate
