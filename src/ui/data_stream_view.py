"""数据流监控显示框。

不绘制波形，以文本/数值方式实时显示：
- 最新样本数值（每通道最近若干帧原始值）
- 实时帧率 / 标称采样率 / 丢帧数
- 累计帧数 / 已采集时长
- 运行状态日志

StreamStats 为线程安全的统计对象，采集线程(LSL 接收线程或 PLUX 回调线程)
高频写入，GUI 以 10Hz 定时读取快照刷新，避免跨线程刷控件。
"""

import time
import threading
from collections import deque
from datetime import datetime
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit
)
from PySide6.QtCore import QTimer


class StreamStats:
    """线程安全的数据流统计（采集线程写，GUI 线程读）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset([], 0)
        self._logs: deque = deque(maxlen=500)
        self._log_seq = 0

    def reset(self, channel_labels: Sequence[str], nominal_rate: float):
        """采集开始时重置。"""
        with self._lock:
            self._labels = list(channel_labels)
            self._nominal_rate = float(nominal_rate)
            self._t0 = time.time()
            self._frame_count = 0
            self._dropped = 0
            self._recent_ts: deque = deque()       # 近2秒的墙钟时间，用于帧率
            self._latest: deque = deque(maxlen=8)  # 最近8帧 (wall_time, sample, src_ts)
            self._last_src_ts: Optional[float] = None
            self._last_idx: Optional[int] = None
            self._interval = (1.0 / nominal_rate) if nominal_rate > 0 else 0

    def on_frame(self, sample: Sequence[float],
                 source_ts: Optional[float] = None,
                 frame_idx: Optional[int] = None):
        """记录一帧数据（采集线程调用）。"""
        now = time.time()
        with self._lock:
            self._frame_count += 1

            # 丢帧检测：优先用帧序号，其次用源时间戳间隔
            if frame_idx is not None and self._last_idx is not None:
                gap_idx = frame_idx - self._last_idx - 1
                if gap_idx > 0:
                    self._dropped += gap_idx
            elif (source_ts is not None and self._last_src_ts is not None
                  and self._interval > 0):
                gap = source_ts - self._last_src_ts
                if gap > 1.5 * self._interval:
                    self._dropped += int(round(gap / self._interval)) - 1

            if frame_idx is not None:
                self._last_idx = frame_idx
            if source_ts is not None:
                self._last_src_ts = source_ts

            self._recent_ts.append(now)
            cutoff = now - 1.0
            while self._recent_ts and self._recent_ts[0] < cutoff:
                self._recent_ts.popleft()

            self._latest.append((now, list(sample), source_ts))

    def add_log(self, message: str):
        """添加一条状态日志。"""
        with self._lock:
            self._log_seq += 1
            self._logs.append((self._log_seq, datetime.now().strftime("%H:%M:%S"),
                               message))

    def snapshot(self) -> dict:
        """读取当前统计快照（GUI 线程定时调用）。"""
        with self._lock:
            now = time.time()
            cutoff = now - 1.0
            while self._recent_ts and self._recent_ts[0] < cutoff:
                self._recent_ts.popleft()

            return {
                "labels": list(self._labels),
                "nominal_rate": self._nominal_rate,
                "frame_count": self._frame_count,
                "dropped": self._dropped,
                "fps": float(len(self._recent_ts)),
                "elapsed": now - self._t0 if self._frame_count > 0 else 0.0,
                "latest": list(self._latest),
                "logs": list(self._logs),
            }


class DataStreamView(QWidget):
    """数据流监控显示框。"""

    def __init__(self, stats: StreamStats):
        super().__init__()
        self._stats = stats
        self._last_log_seq = 0
        self._init_ui()

        # 10Hz 刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(100)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 统计信息区 ──
        stat_group = QGroupBox("数据流状态")
        grid = QGridLayout(stat_group)

        self._lbl_elapsed = QLabel("--:--:--")
        self._lbl_frames = QLabel("0")
        self._lbl_fps = QLabel("--")
        self._lbl_nominal = QLabel("--")
        self._lbl_dropped = QLabel("0")
        self._lbl_channels = QLabel("0")

        big = "font-size: 15px; font-weight: bold; color: #2c3e50;"
        for lbl in (self._lbl_elapsed, self._lbl_frames, self._lbl_fps,
                    self._lbl_nominal, self._lbl_dropped, self._lbl_channels):
            lbl.setStyleSheet(big)

        items = [
            ("已采集时长", self._lbl_elapsed),
            ("累计帧数", self._lbl_frames),
            ("实时帧率(fps)", self._lbl_fps),
            ("标称采样率(Hz)", self._lbl_nominal),
            ("丢帧数", self._lbl_dropped),
            ("启用通道", self._lbl_channels),
        ]
        for col, (title, value) in enumerate(items):
            box = QVBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("color: #7f8c8d;")
            box.addWidget(t)
            box.addWidget(value)
            grid.addLayout(box, 0, col)

        layout.addWidget(stat_group)

        # ── 最新样本数值 ──
        sample_group = QGroupBox("最新样本数值（最近 8 帧）")
        s_layout = QVBoxLayout(sample_group)
        self._sample_table = QTableWidget(0, 1)
        self._sample_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self._sample_table.verticalHeader().setVisible(False)
        self._sample_table.setEditTriggers(QTableWidget.NoEditTriggers)
        s_layout.addWidget(self._sample_table)
        layout.addWidget(sample_group, stretch=1)

        # ── 状态日志 ──
        log_group = QGroupBox("运行状态日志")
        l_layout = QVBoxLayout(log_group)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas, monospace; font-size: 12px; }"
        )
        l_layout.addWidget(self._log_view)
        layout.addWidget(log_group, stretch=1)

    def configure(self, channel_labels: Sequence[str], nominal_rate: float):
        """采集开始：按通道重建表格列。"""
        self._stats.reset(channel_labels, nominal_rate)
        self._last_log_seq = 0
        self._log_view.clear()

        self._sample_table.setColumnCount(len(channel_labels) + 1)
        headers = ["时间"] + [str(lb) for lb in channel_labels]
        self._sample_table.setHorizontalHeaderLabels(headers)
        self._sample_table.setRowCount(0)
        self._lbl_nominal.setText(f"{nominal_rate:g}")
        self._lbl_channels.setText(str(len(channel_labels)))

    def append_log(self, message: str):
        """外部直接写日志（线程安全，实际由定时器刷出）。"""
        self._stats.add_log(message)

    @staticmethod
    def _fmt_duration(sec: float) -> str:
        sec = int(sec)
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _refresh(self):
        """定时刷新界面（10Hz）。"""
        snap = self._stats.snapshot()

        if snap["nominal_rate"] > 0 or snap["frame_count"] > 0:
            self._lbl_elapsed.setText(self._fmt_duration(snap["elapsed"]))
            self._lbl_frames.setText(f"{snap['frame_count']:,}")
            self._lbl_fps.setText(f"{snap['fps']:.0f}")
            dropped = snap["dropped"]
            self._lbl_dropped.setText(str(dropped))
            # 有丢帧时标红提醒
            self._lbl_dropped.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #c0392b;"
                if dropped > 0 else
                "font-size: 15px; font-weight: bold; color: #2c3e50;"
            )

        # 最新样本表格
        latest = snap["latest"]
        if latest:
            self._sample_table.setRowCount(len(latest))
            for row, (wall_t, sample, src_ts) in enumerate(latest):
                ts_text = datetime.fromtimestamp(wall_t).strftime("%H:%M:%S.%f")[:-3]
                self._sample_table.setItem(row, 0, QTableWidgetItem(ts_text))
                for col, val in enumerate(sample):
                    self._sample_table.setItem(
                        row, col + 1,
                        QTableWidgetItem(f"{val:.4f}")
                    )
            self._sample_table.scrollToBottom()

        # 增量刷新日志
        logs = snap["logs"]
        new_lines = [f"[{t}] {msg}" for seq, t, msg in logs
                     if seq > self._last_log_seq]
        if new_lines:
            self._last_log_seq = logs[-1][0]
            self._log_view.appendPlainText("\n".join(new_lines))
