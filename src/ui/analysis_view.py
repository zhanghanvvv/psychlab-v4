"""离线分析界面。

加载已录制的 HDF5 文件，显示全程波形，按信号类型执行分析，
并提供以下增强功能：
- 原始 ADC 值 / 物理量切换
- 分析结果可视化（R 波标记、HRV 散点、频谱、SCR 事件等）
- 三态分段对比（静息/任务/恢复）
- Excel 分析报告导出
"""

import numpy as np
from typing import Optional
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QMessageBox, QSplitter,
    QDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt
from pathlib import Path

from ..storage.hdf5_reader import HDF5Reader, RecordingData
from ..storage.csv_exporter import CSVExporter
from ..analysis.filters import apply_sensor_filter
from ..analysis.ecg_analysis import analyze_ecg, ECGResult
from ..analysis.emg_analysis import analyze_emg, EMGResult
from ..analysis.eda_analysis import analyze_eda, EDAResult
from ..analysis.eeg_analysis import analyze_eeg, EEGResult
from ..analysis.respiration_analysis import analyze_respiration, RespirationResult
from ..analysis.signal_calibration import calibrate_signal, get_sensor_unit
from ..device.sensor_types import get_sensor_meta, SENSOR_META
from ..utils.logger import logger


# 三态对比的阶段定义
PHASE_LABELS = {
    "rest": "静息态",
    "task": "任务态",
    "recovery": "恢复态",
    # 兼容中文直写
    "静息态": "静息态",
    "任务态": "任务态",
    "恢复态": "恢复态",
}


class AnalysisView(QWidget):
    """离线分析面板。"""

    def __init__(self):
        super().__init__()
        self._recording: Optional[RecordingData] = None
        self._filtered_data: Optional[np.ndarray] = None
        self._sensor_types: list[str] = []
        # 最近一次分析结果与对应元数据（供报告导出使用）
        self._last_result = None
        self._last_stype: str = ""
        self._last_channel: int = -1
        self._last_fs: int = 0
        self._init_ui()

    # ────────────────────────────── UI 构建 ──────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 文件操作行 ──
        file_row = QHBoxLayout()
        self._load_btn = QPushButton("打开 HDF5 文件")
        self._load_btn.clicked.connect(self._on_load_file)
        file_row.addWidget(self._load_btn)

        self._file_label = QLabel("未加载文件")
        file_row.addWidget(self._file_label)
        file_row.addStretch()

        self._compare_btn = QPushButton("对比模式")
        self._compare_btn.clicked.connect(self._on_compare)
        file_row.addWidget(self._compare_btn)

        self._export_report_btn = QPushButton("导出报告")
        self._export_report_btn.setEnabled(False)
        self._export_report_btn.clicked.connect(self._on_export_report)
        file_row.addWidget(self._export_report_btn)

        self._export_csv_btn = QPushButton("导出 CSV")
        self._export_csv_btn.setEnabled(False)
        self._export_csv_btn.clicked.connect(self._on_export_csv)
        file_row.addWidget(self._export_csv_btn)
        layout.addLayout(file_row)

        # ── 通道与时间选择行 ──
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel("选择通道:"))
        self._channel_combo = QComboBox()
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._channel_combo)

        ch_row.addWidget(QLabel("起始(秒):"))
        self._start_spin = pg.SpinBox()
        self._start_spin.setRange(0, 1000000)
        self._start_spin.setValue(0)
        ch_row.addWidget(self._start_spin)

        ch_row.addWidget(QLabel("时长(秒):"))
        self._duration_spin = pg.SpinBox()
        self._duration_spin.setRange(1, 1000000)
        self._duration_spin.setValue(60)
        ch_row.addWidget(self._duration_spin)

        self._analyze_btn = QPushButton("分析")
        self._analyze_btn.clicked.connect(self._on_analyze)
        ch_row.addWidget(self._analyze_btn)

        ch_row.addWidget(QLabel("滤波:"))
        self._filter_check = QCheckBox("启用")
        self._filter_check.setChecked(True)
        ch_row.addWidget(self._filter_check)

        ch_row.addWidget(QLabel("单位:"))
        self._raw_check = QCheckBox("原始 ADC")
        self._raw_check.setChecked(False)
        self._raw_check.stateChanged.connect(self._on_channel_changed)
        ch_row.addWidget(self._raw_check)

        layout.addLayout(ch_row)

        # ── 波形 / 分析图表 / 结果表格 ──
        splitter = QSplitter(Qt.Vertical)

        # 上：原始波形
        self._plot_widget = pg.GraphicsLayoutWidget()
        self._plot_widget.setBackground("k")
        self._waveform_plot = self._plot_widget.addPlot()
        self._waveform_plot.showGrid(x=True, y=True, alpha=0.3)
        self._waveform_plot.setLabel("left", "振幅")
        self._waveform_plot.setLabel("bottom", "时间 (秒)")
        splitter.addWidget(self._plot_widget)

        # 中：分析图表
        self._artifact_widget = pg.GraphicsLayoutWidget()
        self._artifact_widget.setBackground("k")
        splitter.addWidget(self._artifact_widget)

        # 下：结果表格
        self._result_table = QTableWidget(0, 2)
        self._result_table.setHorizontalHeaderLabels(["指标", "值"])
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        splitter.addWidget(self._result_table)

        splitter.setSizes([300, 300, 200])
        layout.addWidget(splitter)
        layout.setStretch(layout.count() - 1, 1)

    # ────────────────────────────── 文件加载 ──────────────────────────────

    def _on_load_file(self):
        """加载 HDF5 文件。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 HDF5 文件", "data", "HDF5 Files (*.h5 *.hdf5)"
        )
        if not file_path:
            return

        self._recording = HDF5Reader.load(file_path)
        if not self._recording:
            QMessageBox.critical(self, "错误", "文件加载失败")
            return

        self._sensor_types = self._parse_sensor_types(self._recording)
        while len(self._sensor_types) < self._recording.n_channels:
            self._sensor_types.append("UNKNOWN")

        phase_str = PHASE_LABELS.get(self._recording.phase, self._recording.phase or "未指定")
        self._file_label.setText(
            f"{Path(file_path).name} | "
            f"{self._recording.n_channels}通道 | "
            f"{self._recording.raw_data.shape[0]}样本 | "
            f"{self._recording.duration_sec:.1f}秒 | "
            f"阶段: {phase_str}"
        )
        self._export_csv_btn.setEnabled(True)
        self._export_report_btn.setEnabled(False)
        self._last_result = None

        self._channel_combo.clear()
        for i, stype in enumerate(self._sensor_types):
            name = SENSOR_META.get(stype, SENSOR_META["UNKNOWN"]).name_cn
            self._channel_combo.addItem(f"通道{i+1}: {name}", i)

        self._on_channel_changed()

    @staticmethod
    def _parse_sensor_types(rec: RecordingData) -> list[str]:
        types: list[str] = []
        for sinfo in rec.sensor_info:
            if isinstance(sinfo, (list, tuple)) and len(sinfo) >= 2:
                types.append(sinfo[1])
            elif isinstance(sinfo, dict):
                types.append(sinfo.get("type", "UNKNOWN"))
            else:
                types.append(str(sinfo))
        return types

    # ────────────────────────────── 波形显示 ──────────────────────────────

    def _get_channel_data(self, idx: int, start: int, end: int
                           ) -> tuple[np.ndarray, str, bool]:
        """提取并预处理通道数据。

        返回: (data, sensor_type, is_calibrated)
        """
        if not self._recording or idx >= len(self._sensor_types):
            return np.array([]), "UNKNOWN", False

        data = self._recording.raw_data[start:end, idx].astype(np.float64)
        stype = self._sensor_types[idx]
        is_calibrated = False

        # ADC→物理量转换（除非用户选择"原始 ADC"）
        if not self._raw_check.isChecked() and stype not in ("TRIG", "SYNC", "EVENT", "MARKER"):
            data = calibrate_signal(data, stype)
            is_calibrated = True

        # 滤波（标定后再滤波，避免滤波器对原始整数饱和）
        if self._filter_check.isChecked():
            data = apply_sensor_filter(data, stype, self._recording.sampling_rate)

        return data, stype, is_calibrated

    def _on_channel_changed(self, *_):
        """通道/单位切换时更新波形。"""
        if not self._recording:
            return

        idx = self._channel_combo.currentData()
        if idx is None:
            return

        start_sec = int(self._start_spin.value())
        duration_sec = int(self._duration_spin.value())
        fs = self._recording.sampling_rate
        start = start_sec * fs
        end = min((start_sec + duration_sec) * fs, len(self._recording.raw_data))
        if start >= end:
            return

        data, stype, is_calibrated = self._get_channel_data(idx, start, end)
        time_axis = np.linspace(start / fs, end / fs, len(data))

        self._waveform_plot.clear()
        self._waveform_plot.plot(time_axis, data, pen=pg.mkPen("c", width=1.5))

        meta = get_sensor_meta(stype)
        if meta.y_range:
            self._waveform_plot.setYRange(*meta.y_range)
        unit_label = meta.unit if is_calibrated else "raw ADC"
        self._waveform_plot.setLabel("left", f"{meta.name_cn} ({unit_label})")

    # ────────────────────────────── 分析执行 ──────────────────────────────

    def _on_analyze(self):
        """执行分析。"""
        if not self._recording:
            return

        idx = self._channel_combo.currentData()
        if idx is None:
            return

        fs = self._recording.sampling_rate
        start = int(self._start_spin.value()) * fs
        duration = int(self._duration_spin.value()) * fs
        end = min(start + duration, len(self._recording.raw_data))
        if start >= end:
            QMessageBox.warning(self, "警告", "无效的时间范围")
            return

        data, stype, is_calibrated = self._get_channel_data(idx, start, end)
        time_axis = np.linspace(start / fs, end / fs, len(data))

        self._result_table.setRowCount(0)
        self._artifact_widget.clear()
        self._last_result = None

        # 分析结果元数据
        self._last_stype = stype
        self._last_channel = idx
        self._last_fs = fs

        try:
            if stype == "ECG":
                result = analyze_ecg(data, fs)
                self._fill_ecg_result(result)
                self._plot_ecg_artifacts(result, data, time_axis, fs)
                self._last_result = result
            elif stype == "EMG":
                result = analyze_emg(data, fs)
                self._fill_emg_result(result)
                self._plot_emg_artifacts(result, data, time_axis, fs)
                self._last_result = result
            elif stype == "EDA":
                result = analyze_eda(data, fs)
                self._fill_eda_result(result)
                self._plot_eda_artifacts(result, data, time_axis, fs)
                self._last_result = result
            elif stype == "EEG":
                result = analyze_eeg(data, fs)
                self._fill_eeg_result(result)
                self._plot_eeg_artifacts(result, data, time_axis, fs)
                self._last_result = result
            elif stype == "RESP":
                result = analyze_respiration(data, fs)
                self._fill_resp_result(result)
                self._plot_resp_artifacts(result, data, time_axis, fs)
                self._last_result = result
            else:
                self._fill_generic_result(stype, data)
                self._plot_generic_artifacts(data, time_axis)

            self._export_report_btn.setEnabled(self._last_result is not None)
        except Exception as e:
            logger.error(f"分析失败: {e}", exc_info=True)
            QMessageBox.critical(self, "分析错误", f"分析失败:\n{e}")

    # ────────────────────────────── 结果表格 ──────────────────────────────

    def _add_result_row(self, name: str, value: str):
        row = self._result_table.rowCount()
        self._result_table.insertRow(row)
        self._result_table.setItem(row, 0, QTableWidgetItem(name))
        self._result_table.setItem(row, 1, QTableWidgetItem(value))

    def _fill_ecg_result(self, r: ECGResult):
        self._add_result_row("平均心率", f"{r.heart_rate:.1f} bpm")
        self._add_result_row("心搏数", str(r.n_beats))
        if r.sdnn is not None:
            self._add_result_row("SDNN", f"{r.sdnn:.2f} ms")
        if r.rmssd is not None:
            self._add_result_row("RMSSD", f"{r.rmssd:.2f} ms")
        if r.pnn50 is not None:
            self._add_result_row("pNN50", f"{r.pnn50:.2f} %")
        if r.mean_rr is not None:
            self._add_result_row("平均RR", f"{r.mean_rr:.2f} ms")
        if r.lf_power is not None:
            self._add_result_row("LF 功率", f"{r.lf_power:.2f} ms^2")
        if r.hf_power is not None:
            self._add_result_row("HF 功率", f"{r.hf_power:.2f} ms^2")
        if r.lf_hf_ratio is not None:
            self._add_result_row("LF/HF", f"{r.lf_hf_ratio:.2f}")

    def _fill_emg_result(self, r: EMGResult):
        self._add_result_row("RMS", f"{r.rms:.4f} mV")
        self._add_result_row("平均频率(MNF)", f"{r.mean_freq:.1f} Hz")
        self._add_result_row("中值频率(MDF)", f"{r.median_freq:.1f} Hz")
        self._add_result_row("最大振幅", f"{r.max_amplitude:.4f} mV")

    def _fill_eda_result(self, r: EDAResult):
        self._add_result_row("平均SCL", f"{r.mean_scl:.2f} uS")
        self._add_result_row("SCR事件数", str(r.n_scr))
        if len(r.scr_amplitudes) > 0:
            self._add_result_row("平均SCR幅度", f"{np.mean(r.scr_amplitudes):.4f} uS")
            self._add_result_row("最大SCR幅度", f"{np.max(r.scr_amplitudes):.4f} uS")

    def _fill_eeg_result(self, r: EEGResult):
        for band, power in r.band_powers.items():
            self._add_result_row(f"{band} 功率", f"{power:.4f} uV^2")
        self._add_result_row("总功率", f"{r.total_power:.4f}")
        if r.band_powers.get("Alpha", 0) > 0 and r.band_powers.get("Theta", 0) > 0:
            ratio = r.band_powers["Alpha"] / r.band_powers["Theta"]
            self._add_result_row("Alpha/Theta", f"{ratio:.2f}")

    def _fill_resp_result(self, r: RespirationResult):
        self._add_result_row("呼吸频率", f"{r.breathing_rate:.1f} 次/分")
        self._add_result_row("平均幅度", f"{r.mean_amplitude:.2f}")
        if r.ie_ratio is not None:
            self._add_result_row("吸呼比(I/E)", f"{r.ie_ratio:.2f}")

    def _fill_generic_result(self, stype: str, data: np.ndarray):
        self._add_result_row("信号类型", stype)
        self._add_result_row("样本数", str(len(data)))
        self._add_result_row("均值", f"{np.mean(data):.4f}")
        self._add_result_row("标准差", f"{np.std(data):.4f}")
        self._add_result_row("最大值", f"{np.max(data):.4f}")
        self._add_result_row("最小值", f"{np.min(data):.4f}")

    # ────────────────────────────── 分析可视化 ──────────────────────────────

    def _new_artifact_plot(self, title: str, row: int, col: int
                            ) -> pg.PlotItem:
        """在分析图表区创建一个子图。"""
        p = self._artifact_widget.addPlot(row=row, col=col)
        p.showGrid(x=True, y=True, alpha=0.3)
        p.setTitle(title, color="w")
        return p

    def _plot_ecg_artifacts(self, r: ECGResult, data: np.ndarray,
                             time_axis: np.ndarray, fs: int):
        # 子图1: 波形 + R 波标记
        p1 = self._new_artifact_plot("ECG 波形 + R 波标记", 0, 0)
        p1.plot(time_axis, data, pen=pg.mkPen("c", width=1))
        if r.peaks_idx is not None and len(r.peaks_idx) > 0:
            peak_t = time_axis[r.peaks_idx]
            peak_v = data[r.peaks_idx]
            p1.plot(peak_t, peak_v, pen=None,
                    symbol="o", symbolSize=10,
                    symbolBrush="r", symbolPen="r")
        p1.setLabel("left", "振幅")
        p1.setLabel("bottom", "时间 (秒)")

        # 子图2: HRV 散点图（RR 间期序列）
        p2 = self._new_artifact_plot("HRV 散点 (RR 间期)", 0, 1)
        if len(r.rr_intervals) > 0:
            rr_ms = r.rr_intervals * 1000
            idx = np.arange(1, len(rr_ms) + 1)
            p2.plot(idx, rr_ms, pen=None, symbol="o",
                    symbolSize=5, symbolBrush="g")
            mean_rr = float(np.mean(rr_ms))
            p2.addLine(y=mean_rr, pen=pg.mkPen("y", width=1, style=Qt.DashLine))
        else:
            p2.setTitle("HRV 散点 (无 R 波检测)", color="r")
        p2.setLabel("left", "RR (ms)")
        p2.setLabel("bottom", "心搏序号")

    def _plot_emg_artifacts(self, r: EMGResult, data: np.ndarray,
                             time_axis: np.ndarray, fs: int):
        # 子图1: 包络曲线
        p1 = self._new_artifact_plot("EMG 包络 (RMS 滑窗)", 0, 0)
        p1.plot(time_axis, data, pen=pg.mkPen("c", width=0.5, style=Qt.DashLine))
        if r.envelope is not None and len(r.envelope) == len(data):
            p1.plot(time_axis, r.envelope, pen=pg.mkPen("y", width=2))
        p1.setLabel("left", "振幅 (mV)")
        p1.setLabel("bottom", "时间 (秒)")

        # 子图2: 频谱图
        p2 = self._new_artifact_plot("EMG 频谱 (Welch)", 0, 1)
        from scipy.signal import welch
        nperseg = min(len(data), 2048)
        freqs, psd = welch(data, fs=fs, nperseg=nperseg)
        p2.plot(freqs, psd, pen=pg.mkPen("m", width=1.5))
        if r.mean_freq > 0:
            p2.addLine(x=r.mean_freq, pen=pg.mkPen("g", width=1, style=Qt.DashLine),
                        label=f"MNF={r.mean_freq:.1f}Hz")
        if r.median_freq > 0:
            p2.addLine(x=r.median_freq, pen=pg.mkPen("y", width=1, style=Qt.DashLine),
                        label=f"MDF={r.median_freq:.1f}Hz")
        p2.setLabel("left", "PSD")
        p2.setLabel("bottom", "频率 (Hz)")

    def _plot_eda_artifacts(self, r: EDAResult, data: np.ndarray,
                             time_axis: np.ndarray, fs: int):
        # 子图1: SCL 趋势 + 原始
        p1 = self._new_artifact_plot("EDA: SCL 趋势 + SCR 事件", 0, 0)
        p1.plot(time_axis, data, pen=pg.mkPen("c", width=1), name="Raw")
        if r.scl_trend is not None and len(r.scl_trend) == len(data):
            p1.plot(time_axis, r.scl_trend, pen=pg.mkPen("y", width=2), name="SCL")
        # 标记 SCR 峰
        if len(r.scr_onsets) > 0:
            onset_idx = (r.scr_onsets * fs).astype(int)
            onset_idx = onset_idx[onset_idx < len(data)]
            if len(onset_idx) > 0:
                p1.plot(time_axis[onset_idx], data[onset_idx],
                        pen=None, symbol="o", symbolSize=10,
                        symbolBrush="r", symbolPen="r")
        p1.setLabel("left", "EDA (uS)")
        p1.setLabel("bottom", "时间 (秒)")

        # 子图2: SCR 振幅柱状图
        p2 = self._new_artifact_plot("SCR 事件振幅", 0, 1)
        if len(r.scr_amplitudes) > 0:
            bg = pg.BarGraphItem(
                x=np.arange(len(r.scr_amplitudes)) + 1,
                height=r.scr_amplitudes,
                width=0.6, brush="g"
            )
            p2.addItem(bg)
            p2.setLabel("left", "振幅 (uS)")
            p2.setLabel("bottom", "SCR 序号")
        else:
            p2.setTitle("无 SCR 事件", color="r")

    def _plot_eeg_artifacts(self, r: EEGResult, data: np.ndarray,
                             time_axis: np.ndarray, fs: int):
        # 子图1: PSD 频谱
        p1 = self._new_artifact_plot("EEG 功率谱密度 (PSD)", 0, 0)
        if len(r.freqs) > 0 and len(r.psd) > 0:
            p1.plot(r.freqs, r.psd, pen=pg.mkPen("c", width=1.5))
            # 标注频带分界
            for band_name, (low, high) in [
                ("δ", (0.5, 4.0)), ("θ", (4.0, 8.0)),
                ("α", (8.0, 13.0)), ("β", (13.0, 30.0)),
                ("γ", (30.0, 50.0))
            ]:
                p1.addLine(x=low, pen=pg.mkPen("y", width=0.5, style=Qt.DotLine))
        p1.setLogY(True, None)
        p1.setLabel("left", "PSD (uV^2/Hz)")
        p1.setLabel("bottom", "频率 (Hz)")

        # 子图2: 5 频带功率柱状图
        p2 = self._new_artifact_plot("EEG 频带绝对功率", 0, 1)
        bands = list(r.band_powers.keys())
        powers = [r.band_powers[b] for b in bands]
        if bands and any(p > 0 for p in powers):
            bg = pg.BarGraphItem(
                x=np.arange(len(bands)) + 1,
                height=powers,
                width=0.6, brush="m"
            )
            p2.addItem(bg)
            ticks = [(i + 1, b) for i, b in enumerate(bands)]
            p2.getAxis("bottom").setTicks([ticks])
            p2.setLabel("left", "功率 (uV^2)")
        else:
            p2.setTitle("无频带功率", color="r")

    def _plot_resp_artifacts(self, r: RespirationResult, data: np.ndarray,
                              time_axis: np.ndarray, fs: int):
        p1 = self._new_artifact_plot("呼吸: 峰(吸气)/谷(呼气) 标记", 0, 0)
        p1.plot(time_axis, data, pen=pg.mkPen("c", width=1.5))
        if r.peaks is not None and len(r.peaks) > 0:
            peak_t = time_axis[r.peaks]
            peak_v = data[r.peaks]
            p1.plot(peak_t, peak_v, pen=None, symbol="^",
                    symbolSize=10, symbolBrush="g", symbolPen="g")
        if r.troughs is not None and len(r.troughs) > 0:
            tr_t = time_axis[r.troughs]
            tr_v = data[r.troughs]
            p1.plot(tr_t, tr_v, pen=None, symbol="v",
                    symbolSize=10, symbolBrush="r", symbolPen="r")
        p1.setLabel("left", "振幅")
        p1.setLabel("bottom", "时间 (秒)")

        # 子图2: 瞬时呼吸频率
        p2 = self._new_artifact_plot("瞬时呼吸频率", 0, 1)
        if r.rate_series is not None and len(r.rate_series) > 0:
            x = np.arange(1, len(r.rate_series) + 1)
            p2.plot(x, r.rate_series, pen=pg.mkPen("y", width=2),
                    symbol="o", symbolSize=5)
        else:
            p2.setTitle("无法计算瞬时频率", color="r")
        p2.setLabel("left", "频率 (次/分)")
        p2.setLabel("bottom", "呼吸周期序号")

    def _plot_generic_artifacts(self, data: np.ndarray, time_axis: np.ndarray):
        p1 = self._new_artifact_plot("信号波形", 0, 0)
        p1.plot(time_axis, data, pen=pg.mkPen("c", width=1.5))
        p1.setLabel("left", "振幅")
        p1.setLabel("bottom", "时间 (秒)")

    # ────────────────────────────── 对比模式 ──────────────────────────────

    def _on_compare(self):
        """三态对比：选多个 HDF5 文件，横向比较关键指标。"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 2-3 个 HDF5 文件进行对比", "data",
            "HDF5 Files (*.h5 *.hdf5)"
        )
        if not file_paths or len(file_paths) < 2:
            QMessageBox.information(self, "提示", "请至少选择 2 个文件进行对比")
            return
        if len(file_paths) > 3:
            QMessageBox.warning(self, "警告", "最多对比 3 个文件，已截取前 3 个")
            file_paths = file_paths[:3]

        # 加载并解析阶段
        items = []
        for fp in file_paths:
            rec = HDF5Reader.load(fp)
            if not rec:
                QMessageBox.critical(self, "错误", f"加载失败: {fp}")
                return
            phase = rec.phase or ""
            items.append({
                "path": fp,
                "rec": rec,
                "phase": phase,
                "sensor_types": self._parse_sensor_types(rec),
            })

        dlg = PhaseComparisonDialog(items, self)
        dlg.exec()

    # ────────────────────────────── 报告导出 ──────────────────────────────

    def _on_export_report(self):
        """导出 Excel 分析报告。"""
        if self._last_result is None or self._recording is None:
            QMessageBox.warning(self, "提示", "请先执行分析")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel 报告", "data/analysis_report.xlsx",
            "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            from ..analysis.report_exporter import export_report
            ok = export_report(
                result=self._last_result,
                sensor_type=self._last_stype,
                sampling_rate=self._last_fs,
                recording=self._recording,
                file_path=file_path,
            )
            if ok:
                QMessageBox.information(self, "导出成功",
                    f"分析报告已导出:\n{file_path}")
            else:
                QMessageBox.critical(self, "错误", "Excel 报告导出失败")
        except ImportError:
            QMessageBox.critical(self, "依赖缺失",
                "Excel 报告导出需要 openpyxl 库，请运行 pip install openpyxl")
        except Exception as e:
            logger.error(f"报告导出失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败:\n{e}")

    # ────────────────────────────── CSV 导出 ──────────────────────────────

    def _on_export_csv(self):
        """导出CSV。"""
        if not self._recording:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "data/export.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return

        sensor_info = self._recording.sensor_info
        if CSVExporter.export(self._recording, file_path, sensor_info):
            events_path = file_path.replace(".csv", "_events.csv")
            CSVExporter.export_events(self._recording.events, events_path)
            QMessageBox.information(self, "导出成功", f"数据已导出到:\n{file_path}")
        else:
            QMessageBox.critical(self, "错误", "CSV 导出失败")


# ══════════════════════════════════════════════════════════════════════
# 三态分段对比对话框
# ══════════════════════════════════════════════════════════════════════


class PhaseComparisonDialog(QDialog):
    """三态分段对比对话框。

    加载多个 HDF5 文件，自动/手动指派阶段，对每个文件计算
    各通道关键指标，生成横向对比表与柱状图。
    """

    # 用于横向对比的关键指标提取器
    _METRIC_EXTRACTORS = {
        "ECG":  lambda r: {"心率(bpm)": r.heart_rate,
                            "SDNN(ms)": r.sdnn if r.sdnn is not None else float("nan"),
                            "RMSSD(ms)": r.rmssd if r.rmssd is not None else float("nan"),
                            "心搏数": float(r.n_beats)},
        "EMG":  lambda r: {"RMS(mV)": r.rms,
                            "MNF(Hz)": r.mean_freq,
                            "MDF(Hz)": r.median_freq,
                            "最大振幅(mV)": r.max_amplitude},
        "EDA":  lambda r: {"平均SCL(uS)": r.mean_scl,
                            "SCR事件数": float(r.n_scr),
                            "平均SCR幅度(uS)": float(np.mean(r.scr_amplitudes))
                                                if len(r.scr_amplitudes) > 0 else float("nan")},
        "EEG":  lambda r: {**{f"{b}_功率": p for b, p in r.band_powers.items()},
                            "总功率": r.total_power},
        "RESP": lambda r: {"呼吸频率(次/分)": r.breathing_rate,
                            "平均幅度": r.mean_amplitude,
                            "吸呼比": r.ie_ratio if r.ie_ratio is not None else float("nan")},
    }

    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("三态分段对比分析")
        self.resize(1100, 700)
        self._items = items  # [{path, rec, phase, sensor_types}]
        self._phase_assigns: list[str] = []  # 用户指派的阶段
        self._init_ui()
        self._auto_assign_phases()
        self._refresh_phase_combo()
        self._do_compare()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 顶部：阶段指派 ──
        assign_layout = QHBoxLayout()
        assign_layout.addWidget(QLabel("阶段指派:"))
        self._phase_combos: list[QComboBox] = []
        for i, item in enumerate(self._items):
            label = QLabel(f"文件{i+1}: {Path(item['path']).name[:30]}")
            assign_layout.addWidget(label)
            combo = QComboBox()
            combo.addItems(["静息态", "任务态", "恢复态", "其他"])
            self._phase_combos.append(combo)
            combo.currentIndexChanged.connect(self._on_phase_changed)
            assign_layout.addWidget(combo)
        assign_layout.addStretch()
        layout.addLayout(assign_layout)

        # ── 通道选择 ──
        ch_layout = QHBoxLayout()
        ch_layout.addWidget(QLabel("对比通道:"))
        self._channel_combo = QComboBox()
        self._channel_combo.currentIndexChanged.connect(self._do_compare)
        ch_layout.addWidget(self._channel_combo)
        ch_layout.addStretch()
        layout.addLayout(ch_layout)

        # ── 对比内容 Splitter ──
        splitter = QSplitter(Qt.Vertical)

        # 对比柱状图
        self._plot_widget = pg.GraphicsLayoutWidget()
        self._plot_widget.setBackground("k")
        self._bar_plot = self._plot_widget.addPlot()
        self._bar_plot.showGrid(x=True, y=True, alpha=0.3)
        self._bar_plot.setLabel("left", "数值")
        self._bar_plot.setLabel("bottom", "阶段")
        self._bar_plot.setTitle("三态指标对比", color="w")
        splitter.addWidget(self._plot_widget)

        # 对比表
        self._table = QTableWidget(0, 0)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        splitter.addWidget(self._table)

        splitter.setSizes([400, 300])
        layout.addWidget(splitter, 1)

        # ── 底部按钮 ──
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _auto_assign_phases(self):
        """根据 HDF5 attrs.phase 自动指派阶段。"""
        for i, item in enumerate(self._items):
            ph = item["phase"]
            if ph in ("rest", "静息态"):
                self._phase_combos[i].setCurrentText("静息态")
            elif ph in ("task", "任务态"):
                self._phase_combos[i].setCurrentText("任务态")
            elif ph in ("recovery", "恢复态"):
                self._phase_combos[i].setCurrentText("恢复态")
            else:
                # 无阶段信息，按文件顺序指派（文件1=静息，文件2=任务，文件3=恢复）
                default_map = {0: "静息态", 1: "任务态", 2: "恢复态"}
                self._phase_combos[i].setCurrentText(default_map.get(i, "其他"))

    def _refresh_phase_combo(self):
        """刷新通道下拉。"""
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        if not self._items:
            return
        first = self._items[0]
        types = first["sensor_types"]
        for i, stype in enumerate(types):
            name = SENSOR_META.get(stype, SENSOR_META["UNKNOWN"]).name_cn
            self._channel_combo.addItem(f"通道{i+1}: {name}", i)
        self._channel_combo.blockSignals(False)

    def _on_phase_changed(self, *_):
        self._do_compare()

    def _do_compare(self, *_):
        """执行对比并更新表格与图表。"""
        ch_idx = self._channel_combo.currentData()
        if ch_idx is None:
            return

        # 收集每个文件该通道的传感器类型与分析结果
        records = []
        for i, item in enumerate(self._items):
            rec = item["rec"]
            types = item["sensor_types"]
            if ch_idx >= len(types):
                continue
            stype = types[ch_idx]
            data = rec.raw_data[:, ch_idx].astype(np.float64)
            data = calibrate_signal(data, stype)
            data = apply_sensor_filter(data, stype, rec.sampling_rate)

            phase_label = self._phase_combos[i].currentText()
            result = self._analyze_by_type(stype, data, rec.sampling_rate)
            if result is None:
                continue
            records.append({
                "phase": phase_label,
                "stype": stype,
                "result": result,
            })

        if not records:
            return

        stype = records[0]["stype"]
        extractor = self._METRIC_EXTRACTORS.get(stype)
        if extractor is None:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._bar_plot.clear()
            return

        # 提取指标
        metric_names = list(extractor(records[0]["result"]).keys())
        phases = [r["phase"] for r in records]

        # 更新表格
        self._table.setRowCount(len(metric_names))
        self._table.setColumnCount(len(phases) + 1)
        headers = ["指标"] + phases
        self._table.setHorizontalHeaderLabels(headers)
        for r, mname in enumerate(metric_names):
            self._table.setItem(r, 0, QTableWidgetItem(mname))
            for c, rec in enumerate(records):
                val = extractor(rec["result"]).get(mname, float("nan"))
                if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                    txt = "N/A"
                else:
                    txt = f"{val:.3f}" if isinstance(val, float) else str(val)
                self._table.setItem(r, c + 1, QTableWidgetItem(txt))

        # 更新柱状图（取第一个指标作为示例，也可循环展示多个）
        self._bar_plot.clear()
        if metric_names:
            heights = []
            for rec in records:
                val = extractor(rec["result"]).get(metric_names[0], float("nan"))
                heights.append(0.0 if (isinstance(val, float) and
                                       (np.isnan(val) or np.isinf(val)))
                               else float(val))
            x = np.arange(len(phases)) + 1
            bg = pg.BarGraphItem(x=x, height=heights, width=0.6, brush="c")
            self._bar_plot.addItem(bg)
            ticks = [(i + 1, p) for i, p in enumerate(phases)]
            self._bar_plot.getAxis("bottom").setTicks([ticks])
            self._bar_plot.setTitle(f"{metric_names[0]} - 三态对比", color="w")

    @staticmethod
    def _analyze_by_type(stype: str, data: np.ndarray, fs: int):
        try:
            if stype == "ECG":
                return analyze_ecg(data, fs)
            if stype == "EMG":
                return analyze_emg(data, fs)
            if stype == "EDA":
                return analyze_eda(data, fs)
            if stype == "EEG":
                return analyze_eeg(data, fs)
            if stype == "RESP":
                return analyze_respiration(data, fs)
        except Exception as e:
            logger.error(f"对比分析失败 [{stype}]: {e}", exc_info=True)
        return None
