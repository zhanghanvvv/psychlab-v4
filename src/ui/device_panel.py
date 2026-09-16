"""设备连接与配置面板。

提供蓝牙设备扫描、连接、通道配置、采样率设置、采集开始/停止等功能。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QFormLayout, QSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Signal, Qt, QThread
from typing import Optional

from ..device.plux_wrapper import DeviceManager, SensorInfo, DeviceInfo
from ..device.lsl_source import LSLDataSource, LSLStreamInfo, PYLSL_AVAILABLE
from ..device.sensor_types import SENSOR_META
from ..constants import MAX_SAMPLING_RATES, CHANNEL_MASKS
from ..utils.logger import logger
from ..utils.config_manager import ConfigManager


# 数据源类型
SOURCE_PLUX = "plux"   # PLUX 直连
SOURCE_LSL = "lsl"     # LSL 流（如 OpenSignals）

# LSL 通道可手动指派的传感器类型（30+ 种，按类别分组）
ASSIGNABLE_SENSOR_TYPES = [
    # 生物电类
    "ECG", "EMG", "EEG", "EOG", "EGG", "ERG",
    # 阻抗/电导类
    "EDA", "GSR",
    # 心血管与血氧类
    "BVP", "PPG", "OXIMETER", "SpO2", "HR", "ABP",
    # 呼吸类
    "RESP", "RIP", "AIRFLOW", "CO2",
    # 体温类
    "TEMP", "BODYTEMP", "AMBIENTTEMP",
    # 运动与力学类
    "XYZ", "GYRO", "MAG", "FORCE", "PRESSURE", "GONI", "TORQUE",
    # 光照与化学类
    "LIGHT", "UV", "PH", "GLUCOSE",
    # 触发与同步类
    "TRIG", "SYNC", "EVENT", "MARKER",
    # 其他
    "SOUND", "POSITION",
    # 未知
    "UNKNOWN",
]


class _LSLScanWorker(QThread):
    """LSL 流扫描后台线程（resolve_streams 可能耗时 6~8 秒）。"""
    finished = Signal(list)  # List[LSLStreamInfo]

    def __init__(self, lsl_source: LSLDataSource, wait_time: float = 6.0):
        super().__init__()
        self._lsl = lsl_source
        self._wait = wait_time

    def run(self):
        streams = self._lsl.discover_streams(wait_time=self._wait)
        self.finished.emit(streams)


class DevicePanel(QWidget):
    """设备连接配置面板。

    支持两种数据源：
    1. PLUX 直连：通过 PLUX Python API 直接连接 biosignalsplux 设备
    2. LSL 流：接收 OpenSignals 等软件广播的 LSL 生理数据流
    """

    # ── 信号 ──
    connectRequested = Signal(str)       # 蓝牙地址 或 LSL 流名称
    disconnectRequested = Signal()
    acquisitionStartRequested = Signal(int, int)  # 采样率, 通道掩码
    acquisitionStopRequested = Signal()
    sourceTypeChanged = Signal(str)      # 数据源类型变更

    def __init__(self):
        super().__init__()
        self._config = ConfigManager()
        self._device_mgr = DeviceManager()
        self._lsl_source = LSLDataSource()
        self._connected_sensors: list[SensorInfo] = []
        self._selected_channels = set()
        self._current_source = SOURCE_PLUX
        self._lsl_streams: list[LSLStreamInfo] = []
        self._scan_worker: Optional[_LSLScanWorker] = None
        # 各通道是否启用（LSL 流可能广播未接线的通道，需可禁用）
        self._channel_enabled: list[bool] = []

        self._init_ui()
        self._update_ui_state(connected=False)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── 数据源选择 ──
        source_group = QGroupBox("数据源")
        source_layout = QFormLayout(source_group)

        self._source_combo = QComboBox()
        self._source_combo.addItem("PLUX 直连 (蓝牙)", SOURCE_PLUX)
        lsl_text = "LSL 流 (OpenSignals)"
        if not PYLSL_AVAILABLE:
            lsl_text += " [未安装pylsl]"
        self._source_combo.addItem(lsl_text, SOURCE_LSL)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_layout.addRow("数据源:", self._source_combo)

        layout.addWidget(source_group)

        # ── 设备连接组 ──
        conn_group = QGroupBox("设备连接")
        conn_layout = QVBoxLayout(conn_group)

        # 扫描行
        scan_row = QHBoxLayout()
        self._scan_btn = QPushButton("扫描设备")
        self._scan_btn.clicked.connect(self._on_scan)
        scan_row.addWidget(self._scan_btn)

        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(0)
        scan_row.addWidget(self._device_combo)

        self._connect_btn = QPushButton("连接")
        self._connect_btn.clicked.connect(self._on_connect)
        scan_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("断开")
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        scan_row.addWidget(self._disconnect_btn)
        conn_layout.addLayout(scan_row)

        # 设备信息
        info_form = QFormLayout()
        self._battery_label = QLabel("--")
        self._channels_label = QLabel("--")
        self._mode_label = QLabel("--")
        info_form.addRow("电池:", self._battery_label)
        info_form.addRow("通道数:", self._channels_label)
        info_form.addRow("模式:", self._mode_label)
        conn_layout.addLayout(info_form)

        layout.addWidget(conn_group)

        # ── 传感器列表 ──
        sensor_group = QGroupBox("已连接传感器")
        sensor_layout = QVBoxLayout(sensor_group)

        self._sensor_table = QTableWidget(0, 5)
        self._sensor_table.setHorizontalHeaderLabels(
            ["通道", "类型", "名称", "序列号", "启用"]
        )
        # 前几列按内容自适应，"启用"列拉伸填充剩余空间，避免横向滚动
        header = self._sensor_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self._sensor_table.setSelectionBehavior(QTableWidget.SelectRows)
        sensor_layout.addWidget(self._sensor_table)

        layout.addWidget(sensor_group)

        # ── 采集配置组 ──
        acq_group = QGroupBox("采集配置")
        acq_form = QFormLayout(acq_group)

        # 采集阶段：静息态 / 任务态 / 恢复态 分开独立采集
        self._phase_combo = QComboBox()
        self._phase_combo.addItem("静息态", "静息态")
        self._phase_combo.addItem("任务态", "任务态")
        self._phase_combo.addItem("恢复态", "恢复态")
        acq_form.addRow("采集阶段:", self._phase_combo)

        self._rate_combo = QComboBox()
        for rate in self._config.get("supported_sampling_rates", [1000]):
            self._rate_combo.addItem(f"{rate} Hz", rate)
        default_idx = self._rate_combo.findData(
            self._config.get("default_sampling_rate", 1000)
        )
        if default_idx >= 0:
            self._rate_combo.setCurrentIndex(default_idx)
        self._rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        acq_form.addRow("采样率:", self._rate_combo)

        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(0, 36000)  # 最大10小时(秒)
        self._duration_spin.setValue(0)
        self._duration_spin.setSuffix(" 秒")
        self._duration_spin.setSpecialValueText("连续(不自动停止)")
        acq_form.addRow("采集时长:", self._duration_spin)

        layout.addWidget(acq_group)

        # ── 采集控制 ──
        ctrl_row = QHBoxLayout()
        self._start_btn = QPushButton("开始采集")
        self._start_btn.setMinimumHeight(40)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; "
            "font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #229954; }"
        )
        self._start_btn.clicked.connect(self._on_start_acquisition)
        ctrl_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止采集")
        self._stop_btn.setMinimumHeight(40)
        self._stop_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; color: white; "
            "font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #c0392b; }"
        )
        self._stop_btn.clicked.connect(self._on_stop_acquisition)
        ctrl_row.addWidget(self._stop_btn)

        layout.addLayout(ctrl_row)
        layout.addStretch()

    def _on_source_changed(self):
        """数据源切换。"""
        self._current_source = self._source_combo.currentData()
        self._device_combo.clear()
        self._connected_sensors.clear()
        self._channel_enabled.clear()
        self._sensor_table.setRowCount(0)
        self._battery_label.setText("--")
        self._channels_label.setText("--")

        if self._current_source == SOURCE_LSL:
            self._mode_label.setText("LSL 流模式")
            self._scan_btn.setText("扫描 LSL 流")
            if not PYLSL_AVAILABLE:
                QMessageBox.warning(self, "提示",
                    "pylsl 未安装，LSL 模式不可用。\n请运行: pip install pylsl")
                self._source_combo.setCurrentIndex(0)
                return
        else:
            self._mode_label.setText("PLUX 直连")
            self._scan_btn.setText("扫描设备")

        self.sourceTypeChanged.emit(self._current_source)
        self._update_ui_state(connected=False)

    def _on_scan(self):
        """扫描设备/LSL流。"""
        self._device_combo.clear()

        if self._current_source == SOURCE_LSL:
            if not PYLSL_AVAILABLE:
                QMessageBox.warning(self, "错误", "pylsl 未安装")
                return
            # 后台线程扫描（实测发现流可能需要 6~8 秒，避免界面卡死）
            self._scan_btn.setEnabled(False)
            self._connect_btn.setEnabled(False)
            self._scan_btn.setText("扫描中(约8秒)...")
            self._device_combo.clear()
            self._scan_worker = _LSLScanWorker(self._lsl_source, wait_time=8.0)
            self._scan_worker.finished.connect(self._on_lsl_scan_finished)
            self._scan_worker.start()
        else:
            addresses = self._device_mgr.discover()
            for addr in addresses:
                label = addr if not self._device_mgr.is_mock else f"{addr} (模拟设备)"
                self._device_combo.addItem(label, addr)
            if not addresses:
                QMessageBox.information(self, "扫描结果", "未发现设备")

    def _on_lsl_scan_finished(self, streams: list):
        """LSL 扫描完成（后台线程回调）。"""
        self._scan_btn.setEnabled(True)
        self._connect_btn.setEnabled(True)
        self._scan_btn.setText("扫描 LSL 流")
        self._lsl_streams = streams

        for s in streams:
            label = f"{s.name} | {s.stream_type} | {s.channel_count}ch @ {s.nominal_srate:g}Hz"
            self._device_combo.addItem(label, s.name)

        if not streams:
            QMessageBox.information(
                self, "扫描结果",
                "未发现 LSL 流。请检查：\n"
                "1. OpenSignals 是否已启动\n"
                "2. OpenSignals 中是否已连接设备并开始采集\n"
                "3. OpenSignals 设置中是否启用 LSL streaming\n"
                "4. 防火墙是否阻止了网络发现(可尝试专用网络)"
            )
        else:
            self.status_message = f"发现 {len(streams)} 个 LSL 流"

    def _on_connect(self):
        """连接设备/LSL流。"""
        idx = self._device_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "错误", "请先扫描并选择数据源")
            return

        if self._current_source == SOURCE_LSL:
            self._connect_lsl()
        else:
            self._connect_plux()

    def _connect_plux(self):
        """连接 PLUX 设备。"""
        address = self._device_combo.currentData()
        if self._device_mgr.connect(address):
            sensors = self._device_mgr.get_connected_sensors()
            self._update_sensor_table(sensors)
            self._update_ui_state(connected=True)

            info = self._device_mgr.device_info
            if info:
                self._battery_label.setText(f"{info.battery}%")
                self._channels_label.setText(str(info.channels))
                self._mode_label.setText(
                    "模拟模式" if self._device_mgr.is_mock else "PLUX 真实设备"
                )
            self.connectRequested.emit(address)

    def _connect_lsl(self):
        """连接 LSL 流。"""
        stream_name = self._device_combo.currentData()
        stream = next((s for s in self._lsl_streams if s.name == stream_name), None)
        if stream is None:
            QMessageBox.warning(self, "错误", "请重新扫描 LSL 流")
            return

        self._connect_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)

        # 直接使用发现阶段保存的原始流对象（不再二次解析）
        ok = self._lsl_source.connect(stream, on_data=lambda data, ts: None)
        self._connect_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)

        if not ok:
            QMessageBox.critical(
                self, "连接失败",
                f"无法连接 LSL 流: {stream.name}\n"
                "请确认 OpenSignals 仍在运行并正在采集数据。"
            )
            return

        # 生成传感器列表（OpenSignals 不提供通道标签，默认 UNKNOWN，
        # 用户可在表格“类型”列下拉框中手动指派 ECG/EMG/EDA 等）
        sensors = []
        for i in range(stream.channel_count):
            ch_name = (stream.channel_names[i] if stream.channel_names
                       and i < len(stream.channel_names) else f"ch{i+1}")
            stype = self._infer_sensor_type(ch_name)
            meta = SENSOR_META.get(stype, SENSOR_META["UNKNOWN"])
            sensors.append(SensorInfo(
                port=i + 1,
                sensor_type=stype,
                sensor_name_cn=meta.name_cn,
                serial_num="LSL",
                color="",
            ))

        self._update_sensor_table_lsl(sensors)
        self._update_ui_state(connected=True)
        self._battery_label.setText("N/A (LSL)")
        self._channels_label.setText(str(stream.channel_count))
        self._mode_label.setText(f"LSL: {stream.name}")
        self.connectRequested.emit(stream_name)

    def _infer_sensor_type(self, channel_name: str) -> str:
        """从 LSL 通道名称推断传感器类型。"""
        name_lower = channel_name.upper()
        mapping = {
            "ECG": "ECG", "EKG": "ECG", "HEART": "ECG",
            "EMG": "EMG", "MUSCLE": "EMG",
            "EEG": "EEG", "BRAIN": "EEG",
            "EDA": "EDA", "GSR": "EDA", "SKIN": "EDA",
            "BVP": "BVP", "PPG": "BVP", "PULSE": "BVP", "血氧": "BVP",
            "RESP": "RESP", "BREATH": "RESP", "呼吸": "RESP",
            "TEMP": "TEMP", "体温": "TEMP",
            "EOG": "EOG", "眼电": "EOG",
            "EGG": "EGG", "胃电": "EGG",
            "SPO2": "OXIMETER", "OXY": "OXIMETER",
        }
        for key, value in mapping.items():
            if key in name_lower:
                return value
        return "UNKNOWN"

    def _on_disconnect(self):
        """断开设备/LSL流。"""
        if self._current_source == SOURCE_LSL:
            self._lsl_source.close()
        else:
            self._device_mgr.disconnect()

        self._connected_sensors.clear()
        self._channel_enabled.clear()
        self._sensor_table.setRowCount(0)
        self._battery_label.setText("--")
        self._channels_label.setText("--")
        self._update_ui_state(connected=False)
        self.disconnectRequested.emit()

    def _update_sensor_table(self, sensors: list[SensorInfo]):
        """更新传感器表格（PLUX 模式，类型只读，全部启用）。"""
        self._connected_sensors = sensors
        self._channel_enabled = [True] * len(sensors)
        self._sensor_table.setRowCount(len(sensors))
        for i, sensor in enumerate(sensors):
            self._sensor_table.setItem(i, 0, QTableWidgetItem(str(sensor.port)))
            self._sensor_table.setItem(i, 1, QTableWidgetItem(sensor.sensor_type))
            self._sensor_table.setItem(i, 2, QTableWidgetItem(sensor.sensor_name_cn))
            self._sensor_table.setItem(i, 3, QTableWidgetItem(sensor.serial_num))
            item = QTableWidgetItem("—")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._sensor_table.setItem(i, 4, item)

    def _update_sensor_table_lsl(self, sensors: list[SensorInfo]):
        """更新传感器表格（LSL 模式，“类型”列可下拉指派，“启用”列可勾选）。

        OpenSignals 的 LSL 流不携带通道信号类型信息，
        需要用户按实际接线为每个通道指派 ECG/EMG/RESP 等类型；
        未接线的通道（OpenSignals 仍会广播）可取消勾选，
        采集/绘图/存储将只作用于勾选的通道。
        """
        self._connected_sensors = list(sensors)
        self._channel_enabled = [True] * len(sensors)
        self._sensor_table.setRowCount(len(sensors))
        for i, sensor in enumerate(sensors):
            self._sensor_table.setItem(i, 0, QTableWidgetItem(str(sensor.port)))

            # 类型下拉框
            combo = QComboBox()
            for stype in ASSIGNABLE_SENSOR_TYPES:
                meta = SENSOR_META.get(stype, SENSOR_META["UNKNOWN"])
                combo.addItem(f"{stype} ({meta.name_cn})", stype)
            # 选中当前推断类型
            idx = combo.findData(sensor.sensor_type)
            combo.setCurrentIndex(idx if idx >= 0 else len(ASSIGNABLE_SENSOR_TYPES) - 1)
            combo.currentIndexChanged.connect(
                lambda _ci, row=i, c=combo: self._on_lsl_type_changed(row, c.currentData())
            )
            self._sensor_table.setCellWidget(i, 1, combo)

            name_item = QTableWidgetItem(sensor.sensor_name_cn)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._sensor_table.setItem(i, 2, name_item)
            self._sensor_table.setItem(i, 3, QTableWidgetItem(sensor.serial_num))

            # 启用勾选框（居中）
            chk = QCheckBox()
            chk.setChecked(True)
            chk.stateChanged.connect(
                lambda state, row=i: self._on_channel_enabled_changed(row, state)
            )
            chk_wrap = QWidget()
            chk_layout = QHBoxLayout(chk_wrap)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self._sensor_table.setCellWidget(i, 4, chk_wrap)

    def _on_channel_enabled_changed(self, row: int, state: int):
        """通道启用/禁用勾选回调。state: Qt.CheckState。"""
        if 0 <= row < len(self._channel_enabled):
            self._channel_enabled[row] = (state == Qt.Checked.value)
            active = sum(self._channel_enabled)
            logger.info(f"通道{row+1} 启用状态 -> {self._channel_enabled[row]}，"
                        f"当前启用 {active}/{len(self._channel_enabled)} 通道")

    def _on_lsl_type_changed(self, row: int, sensor_type: str):
        """用户在 LSL 表格中手动修改通道类型。"""
        if 0 <= row < len(self._connected_sensors):
            s = self._connected_sensors[row]
            meta = SENSOR_META.get(sensor_type, SENSOR_META["UNKNOWN"])
            self._connected_sensors[row] = SensorInfo(
                port=s.port,
                sensor_type=sensor_type,
                sensor_name_cn=meta.name_cn,
                serial_num=s.serial_num,
                color=s.color,
            )
            # 同步名称列
            name_item = self._sensor_table.item(row, 2)
            if name_item:
                name_item.setText(meta.name_cn)

    def _on_rate_changed(self):
        """采样率变更时检查通道数约束。"""
        n_channels = len(self._connected_sensors)
        if n_channels == 0:
            return
        max_rate = MAX_SAMPLING_RATES.get(n_channels, 1000)
        selected_rate = self._rate_combo.currentData()
        if selected_rate > max_rate:
            QMessageBox.warning(
                self, "采样率限制",
                f"{n_channels}通道时最大采样率为 {max_rate} Hz"
            )
            idx = self._rate_combo.findData(max_rate)
            if idx >= 0:
                self._rate_combo.setCurrentIndex(idx)

    def _on_start_acquisition(self):
        """开始采集。"""
        n_channels = len(self._connected_sensors)
        if n_channels == 0:
            QMessageBox.warning(self, "错误", "无传感器连接，请先连接设备")
            return

        n_active = sum(self._channel_enabled)
        if n_active == 0:
            QMessageBox.warning(self, "错误",
                "至少需要启用 1 个通道（勾选传感器表“启用”列）")
            return

        rate = self._rate_combo.currentData()
        mask = CHANNEL_MASKS.get(n_channels, 0xFF)

        self.acquisitionStartRequested.emit(rate, mask)

    def _on_stop_acquisition(self):
        """停止采集。"""
        self.acquisitionStopRequested.emit()

    def _update_ui_state(self, connected: bool):
        """更新UI控件状态。"""
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)
        self._scan_btn.setEnabled(not connected)
        self._start_btn.setEnabled(connected)
        self._stop_btn.setEnabled(False)

    def set_acquisition_running(self, running: bool):
        """设置采集运行状态。"""
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._disconnect_btn.setEnabled(not running)
        # 采集期间锁定阶段选择与通道配置
        self._phase_combo.setEnabled(not running)
        for row in range(self._sensor_table.rowCount()):
            combo = self._sensor_table.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                combo.setEnabled(not running)
            chk_wrap = self._sensor_table.cellWidget(row, 4)
            if chk_wrap is not None:
                chk = chk_wrap.findChild(QCheckBox)
                if chk:
                    chk.setEnabled(not running)

    def update_battery(self, level: int):
        """更新电池显示。"""
        self._battery_label.setText(f"{level}%")

    @property
    def device_manager(self) -> DeviceManager:
        return self._device_mgr

    @property
    def connected_sensors(self) -> list[SensorInfo]:
        return self._connected_sensors

    @property
    def active_sensors(self) -> list[SensorInfo]:
        """当前启用（勾选）的传感器列表。"""
        return [s for s, en in zip(self._connected_sensors, self._channel_enabled)
                if en]

    @property
    def active_channel_indices(self) -> list[int]:
        """启用通道在原始 LSL 帧中的列索引（0 基）。"""
        return [i for i, en in enumerate(self._channel_enabled) if en]

    def get_phase(self) -> str:
        """获取本次采集选择的阶段（静息态/任务态/恢复态）。"""
        return self._phase_combo.currentData()

    def get_duration(self) -> int:
        """获取设置采集时长（秒），0=连续模式。"""
        return self._duration_spin.value()
