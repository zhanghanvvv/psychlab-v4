"""PsychLab V4 主窗口。

整合设备面板、数据流监控、实验阶段控制、离线分析。
管理采集生命周期：设备连接 → 三态阶段切换 → 数据采集 → 存储 → 分析。
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QLabel, QStatusBar, QMenuBar, QMenu, QMessageBox,
    QFileDialog, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QTimer

from .device_panel import DevicePanel, SOURCE_PLUX, SOURCE_LSL
from .data_stream_view import DataStreamView, StreamStats
from .analysis_view import AnalysisView

from ..acquisition.acquisition_worker import AcquisitionWorker
from ..acquisition.ring_buffer import RingBuffer
from ..acquisition.task_controller import TaskController

from ..device.plux_wrapper import SensorInfo
from ..device.lsl_source import LSLDataSource
from ..storage.hdf5_writer import HDF5Writer
from ..storage.streaming_csv_writer import StreamingCSVWriter
from ..utils.config_manager import ConfigManager
from ..utils.logger import logger


class MainWindow(QMainWindow):
    """PsychLab V4 主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PsychLab V4 - 生理信号采集分析系统")
        self.setMinimumSize(1280, 800)

        self._config = ConfigManager()
        self._task_controller = TaskController()
        self._stream_stats = StreamStats()
        self._worker: Optional[AcquisitionWorker] = None
        self._ring_buffer: Optional[RingBuffer] = None
        self._hdf5_writer: Optional[HDF5Writer] = None
        self._csv_writer: Optional[StreamingCSVWriter] = None
        self._is_acquiring = False
        self._finalized = False  # 结束流程防重入（worker信号与手动停止可能同时触发）
        self._sensor_labels: list[str] = []
        self._sensor_info_for_storage: list = []
        self._current_source = SOURCE_PLUX

        self._init_ui()
        self._init_menu()
        self._init_status_bar()
        self._init_timer()

        # 模式提示
        from ..device.plux_wrapper import _plux_available
        if not _plux_available:
            self.statusBar().showMessage("PLUX API 不可用 - 模拟设备模式", 5000)

    # ── 数据源属性 ──
    @property
    def current_source(self) -> str:
        return self._current_source

    @property
    def lsl_source(self) -> Optional[LSLDataSource]:
        return self._device_panel._lsl_source

    def _init_ui(self):
        """初始化主界面布局。"""
        central = QWidget()
        layout = QHBoxLayout(central)

        # ── 左侧面板（设备连接/采集配置，阶段在采集配置中下拉选择）──
        self._device_panel = DevicePanel()

        left_scroll = QScrollArea()
        left_scroll.setWidget(self._device_panel)
        left_scroll.setWidgetResizable(True)
        # 左侧宽度跟随内容，禁用横向滚动条，仅保留纵向滚动
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(360)
        left_scroll.setMaximumWidth(520)

        # ── 右侧（数据流监控/离线分析 Tab）──
        self._tab_widget = QTabWidget()
        self._data_stream_view = DataStreamView(self._stream_stats)
        self._analysis_view = AnalysisView()
        self._tab_widget.addTab(self._data_stream_view, "数据流监控")
        self._tab_widget.addTab(self._analysis_view, "离线分析")

        # 主分割
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_scroll)
        main_splitter.addWidget(self._tab_widget)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)

        layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # 连接信号
        self._connect_signals()

    def _connect_signals(self):
        """连接各组件信号。"""
        self._device_panel.acquisitionStartRequested.connect(
            self._on_start_acquisition
        )
        self._device_panel.acquisitionStopRequested.connect(
            self._on_stop_acquisition
        )
        self._device_panel.sourceTypeChanged.connect(self._on_source_type_changed)

    def _on_source_type_changed(self, source_type: str):
        """数据源类型变更回调。"""
        self._current_source = source_type
        logger.info(f"数据源切换为: {source_type}")

    def _init_menu(self):
        """初始化菜单栏。"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件")

        open_action = file_menu.addAction("打开数据文件...")
        open_action.triggered.connect(self._on_open_file)

        export_action = file_menu.addAction("导出数据...")
        file_menu.addAction(export_action)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)

        # 设置菜单
        settings_menu = menubar.addMenu("设置")
        settings_menu.addAction("设备配置...")
        settings_menu.addAction("滤波配置...")

        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        about_action = help_menu.addAction("关于 PsychLab V4")
        about_action.triggered.connect(self._on_about)

    def _init_status_bar(self):
        """初始化状态栏。"""
        self._status_timer_label = QLabel("采集时长: --")
        self._status_frames_label = QLabel("帧数: --")
        self._status_rate_label = QLabel("采样率: --")
        self._status_channels_label = QLabel("通道: --")

        sb = self.statusBar()
        sb.addPermanentWidget(self._status_timer_label)
        sb.addPermanentWidget(self._status_rate_label)
        sb.addPermanentWidget(self._status_channels_label)
        sb.addPermanentWidget(self._status_frames_label)
        sb.showMessage("就绪")

    def _init_timer(self):
        """状态更新定时器。"""
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(1000)  # 每秒更新

    def _update_status(self):
        """更新状态栏（统一从数据流统计读取，PLUX/LSL 两种模式通用）。"""
        if self._is_acquiring:
            snap = self._stream_stats.snapshot()
            elapsed = snap["elapsed"]
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self._status_timer_label.setText(f"采集时长: {mins:02d}:{secs:02d}")
            self._status_frames_label.setText(f"帧数: {snap['frame_count']:,}")
        else:
            self._status_timer_label.setText("采集时长: --")
            self._status_frames_label.setText("帧数: --")

    # ── 采集控制 ──

    def _on_start_acquisition(self, sampling_rate: int, channel_mask: int):
        """开始数据采集（根据数据源类型分派）。"""
        self._finalized = False
        if self._current_source == SOURCE_LSL:
            self._start_lsl_acquisition(sampling_rate)
        else:
            self._start_plux_acquisition(sampling_rate, channel_mask)

    # 阶段中文名 -> 文件名后缀
    _PHASE_SUFFIX = {"静息态": "REST", "任务态": "TASK", "恢复态": "RECOVERY"}

    def _prepare_storage_and_view(self, n_channels: int, sampling_rate,
                                   sensor_labels: list, sensor_info: list,
                                   device_address: str, phase: str):
        """初始化 RingBuffer、数据流监控、HDF5 写入器和 CSV 写入器。"""
        # RingBuffer
        buffer_size = int(sampling_rate) * self._config.get("ring_buffer_duration_sec", 30)
        self._ring_buffer = RingBuffer(n_channels, buffer_size)

        # 传感器标签
        self._sensor_labels = sensor_labels
        self._sensor_info_for_storage = sensor_info

        # 数据流显示框：通道标签形如 "CH1:RESP"
        display_labels = [f"CH{port}:{stype}" for port, stype, _ in sensor_info]
        self._data_stream_view.configure(display_labels, float(sampling_rate))

        # 文件名带阶段标识，三次独立采集文件互不混淆
        data_dir = self._config.get("data_dir", "data")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        phase_suffix = self._PHASE_SUFFIX.get(phase, "")
        name_core = f"psychlab_{timestamp}_{phase_suffix}" if phase_suffix else f"psychlab_{timestamp}"

        hdf5_path = str(Path(data_dir) / f"{name_core}.h5")
        self._hdf5_writer = HDF5Writer(
            file_path=hdf5_path,
            sampling_rate=int(sampling_rate),
            n_channels=n_channels,
            sensor_info=self._sensor_info_for_storage,
            device_address=device_address,
            phase=phase,
        )
        self._hdf5_writer.open()

        # 流式 CSV 写入器（参考 SYNAPSE-DRIVE）
        csv_header = ["timestamp_src", "timestamp_system"]
        for port, stype, _ in sensor_info:
            csv_header.append(f"ch{port}_{stype}")
        csv_path = str(Path(data_dir) / f"{name_core}.csv")
        self._csv_writer = StreamingCSVWriter(csv_path, csv_header)
        self._csv_writer.start()
        self._current_data_files = (hdf5_path, csv_path)
        self._stream_stats.add_log(
            f"存储已打开（阶段:{phase}）: {Path(hdf5_path).name} / {Path(csv_path).name}"
        )

    def _start_plux_acquisition(self, sampling_rate: int, channel_mask: int):
        """PLUX 直连采集模式。"""
        phase = self._device_panel.get_phase()
        device_mgr = self._device_panel.device_manager
        address = device_mgr.device_info.address if device_mgr.device_info else ""
        n_channels = bin(channel_mask).count("1")

        sensors = device_mgr.connected_sensors
        labels = [s.sensor_type for s in sensors]
        info = [(s.port, s.sensor_type, s.sensor_name_cn) for s in sensors]

        self._prepare_storage_and_view(n_channels, sampling_rate, labels, info,
                                       address, phase)
        self._task_controller.set_acquisition_start(phase)

        # 采集时长
        duration = self._device_panel.get_duration()
        duration_sec = duration if duration > 0 else None

        # 创建采集线程
        self._worker = AcquisitionWorker(
            device_address=address,
            sampling_rate=sampling_rate,
            channel_mask=channel_mask,
            duration=duration_sec,
            ring_buffer=self._ring_buffer,
        )

        self._worker.dataReady.connect(self._on_data_ready)
        self._worker.batteryUpdated.connect(self._device_panel.update_battery)
        self._worker.sensorsDetected.connect(self._device_panel._update_sensor_table)
        self._worker.acquisitionStarted.connect(self._on_acq_started)
        self._worker.acquisitionFinished.connect(self._on_acq_finished)
        self._worker.errorOccurred.connect(self._on_acq_error)
        self._worker.statusMessage.connect(lambda msg: self.statusBar().showMessage(msg))

        self._is_acquiring = True
        self._worker.start()

        self._status_rate_label.setText(f"采样率: {sampling_rate} Hz")
        self._status_channels_label.setText(f"通道: {n_channels}")
        self._device_panel.set_acquisition_running(True)
        self._stream_stats.add_log(
            f"开始采集 (PLUX/{phase}): {sampling_rate}Hz, {n_channels} 通道"
        )

    def _start_lsl_acquisition(self, sampling_rate: int):
        """LSL 流采集模式。

        使用已连接的 LSLDataSource 接收数据，通过回调写入 RingBuffer 和存储。
        """
        lsl = self._device_panel._lsl_source
        if not lsl.is_connected:
            QMessageBox.warning(self, "错误", "LSL 流未连接")
            return

        stream_info = lsl.stream_info
        total_channels = stream_info.channel_count
        # LSL 流的采样率以流声明为准
        actual_rate = int(stream_info.nominal_srate) if stream_info.nominal_srate > 0 else sampling_rate

        # 只处理用户勾选启用的通道（未接线通道即使被 OpenSignals 广播也忽略）
        dp = self._device_panel
        sensors = dp.active_sensors
        active_indices = dp.active_channel_indices
        n_channels = len(sensors)

        if n_channels == 0:
            QMessageBox.warning(self, "错误", "至少需要启用 1 个通道")
            return

        phase = dp.get_phase()
        labels = [s.sensor_type for s in sensors]
        # port 保留原始流通道号（1 基），便于事后追溯物理接线
        info = [(s.port, s.sensor_type, s.sensor_name_cn) for s in sensors]

        self._prepare_storage_and_view(
            n_channels, actual_rate, labels, info, stream_info.name, phase
        )

        # LSL 数据回调（运行在 LSL 接收线程）
        self._lsl_n_seq = 0

        def on_lsl_data(sample, lsl_timestamp):
            # 按启用通道索引从原始帧中提取列
            try:
                frame = [sample[i] for i in active_indices]
            except (IndexError, TypeError):
                return  # 流通道数与声明不符的异常帧，丢弃

            self._lsl_n_seq += 1
            # 数据流统计（帧率/丢帧/最新值）
            self._stream_stats.on_frame(frame, source_ts=lsl_timestamp)
            # 写入 RingBuffer
            self._ring_buffer.push_frame(frame)
            # 写入 HDF5
            if self._hdf5_writer:
                self._hdf5_writer.add_data(self._lsl_n_seq, frame)
            # 写入 CSV
            if self._csv_writer:
                sys_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                row = [f"{lsl_timestamp:.6f}", sys_time] + list(frame)
                self._csv_writer.write_row(row)

        lsl._on_data_cb = on_lsl_data
        lsl.start()

        self._task_controller.set_acquisition_start(phase)
        self._is_acquiring = True
        self._worker = None  # LSL 模式不使用 AcquisitionWorker

        ignored = total_channels - n_channels
        ch_text = f"通道: {n_channels}" + (f" (已忽略{ignored}个未启用)" if ignored else "")
        self._status_rate_label.setText(f"采样率: {actual_rate:g} Hz (LSL)")
        self._status_channels_label.setText(ch_text)
        self._device_panel.set_acquisition_running(True)
        self._stream_stats.add_log(
            f"开始采集 (LSL/{phase} {stream_info.name}): {actual_rate:g}Hz, "
            f"启用 {n_channels}/{total_channels} 通道"
        )
        self.statusBar().showMessage("LSL 采集中...", 0)

    def _on_data_ready(self, n_seq, data):
        """PLUX 数据帧回调：统计 + 写入 HDF5 和 CSV。"""
        frame = list(data)
        self._stream_stats.on_frame(frame, frame_idx=n_seq)
        if self._hdf5_writer:
            self._hdf5_writer.add_data(n_seq, data)
        if self._csv_writer:
            sys_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            row = [str(n_seq), sys_time] + list(data)
            self._csv_writer.write_row(row)

    def _on_acq_started(self):
        """PLUX 设备实际开始采集。"""
        self.statusBar().showMessage("采集中...", 0)

    def _on_acq_finished(self):
        """采集已结束（防重入：worker结束信号与手动停止可能同时到达）。"""
        if self._finalized:
            return
        self._finalized = True

        self._is_acquiring = False
        self._task_controller.stop_all()

        # 最终统计快照
        snap = self._stream_stats.snapshot()
        frame_count = snap["frame_count"]
        dropped = snap["dropped"]

        # 保存阶段切换记录到 HDF5
        if self._hdf5_writer:
            for ev in self._task_controller.get_events_as_dict():
                self._hdf5_writer.add_event(
                    timestamp=ev["timestamp"],
                    abs_time=ev["abs_time"],
                    event_type=ev["event_type"],
                    task_id=ev["task_id"],
                    description=ev["description"],
                    n_seq=ev["n_seq"],
                )
            self._hdf5_writer.close()
            self._hdf5_writer = None

        # 停止 CSV 写入
        if self._csv_writer:
            csv_rows = self._csv_writer.rows_written
            csv_path = str(self._csv_writer.file_path)
            self._csv_writer.stop()
            self._csv_writer = None
        else:
            csv_rows = 0
            csv_path = ""

        phase_name = self._task_controller.events[0].phase if self._task_controller.events else ""
        self._stream_stats.add_log(
            f"采集结束（{phase_name}）: 共 {frame_count:,} 帧, 丢帧 {dropped}"
        )

        self._device_panel.set_acquisition_running(False)
        self.statusBar().showMessage("采集结束", 5000)

        QMessageBox.information(
            self, "采集完成",
            f"数据已保存（{phase_name}）\n"
            f"共 {frame_count:,} 帧，丢帧 {dropped}\n"
            f"CSV: {csv_rows} 行\n"
            f"{Path(csv_path).name if csv_path else ''}"
        )

    def _on_acq_error(self, error_msg):
        """采集错误。"""
        self._is_acquiring = False
        self._device_panel.set_acquisition_running(False)
        self._stream_stats.add_log(f"采集错误: {error_msg}")
        QMessageBox.critical(self, "采集错误", error_msg)
        if self._hdf5_writer:
            self._hdf5_writer.close()
            self._hdf5_writer = None
        if self._csv_writer:
            self._csv_writer.stop()
            self._csv_writer = None

    def _on_stop_acquisition(self):
        """停止采集。"""
        self.statusBar().showMessage("正在停止采集...")

        if self._current_source == SOURCE_LSL:
            # LSL 模式：停止 LSL 接收
            lsl = self._device_panel._lsl_source
            lsl.stop()
            self._on_acq_finished()
        elif self._worker:
            self._worker.stop()
            self._worker.wait(5000)
            if self._worker.isRunning():
                self._worker.terminate()
            self._on_acq_finished()

    # ── 菜单回调 ──

    def _on_open_file(self):
        """打开数据文件。"""
        self._tab_widget.setCurrentWidget(self._analysis_view)
        self._analysis_view._on_load_file()

    def _on_about(self):
        """显示关于对话框。"""
        from ..device.plux_wrapper import _plux_available

        mode = "真实设备模式" if _plux_available else "模拟设备模式"
        QMessageBox.about(
            self, "关于 PsychLab V4",
            f"<h2>PsychLab V4</h2>"
            f"<p>生理信号采集分析系统</p>"
            f"<p>版本: {self._config.get('version', '1.0.0')}</p>"
            f"<p>运行模式: {mode}</p>"
            f"<hr>"
            f"<p>支持传感器: EMG/ECG/EEG/EDA/SpO2/EOG/呼吸/体温等30+种</p>"
            f"<p>最大采样率: 4000Hz (3通道)</p>"
            f"<p>蓝牙传输: ≥10m, 电池续航: ≥10h</p>"
            f"<p>静息态 / 任务态 / 恢复态 全程数据采集与自动分段</p>"
        )

    def closeEvent(self, event):
        """关闭窗口事件。"""
        if self._is_acquiring:
            reply = QMessageBox.question(
                self, "确认退出",
                "采集中，确定要退出吗？数据将被保存。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._on_stop_acquisition()
            else:
                event.ignore()
                return

        # 清理
        if self._worker:
            self._worker.stop()
            self._worker.wait(2000)

        # 清理 LSL 源
        try:
            self._device_panel._lsl_source.close()
        except Exception:
            pass

        if self._hdf5_writer:
            self._hdf5_writer.close()

        if self._csv_writer:
            self._csv_writer.stop()

        event.accept()
