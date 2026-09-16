"""HDF5 实时数据写入器。

采集过程中按块追加写入原始数据、时间戳、传感器元数据和事件标记。
HDF5 文件结构：
  /raw_data        (n_seq, n_channels) float64  - 原始数据
  /timestamps     (n_seq,) float64               - 时间戳(相对开始秒数)
  /events          结构化数组                      - 事件标记
  attrs: 采样率、通道数、传感器类型、设备地址、采集时间等元数据
"""

import numpy as np
import h5py
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..utils.logger import logger


class HDF5Writer:
    """HDF5 实时写入器。"""

    def __init__(self, file_path: str, sampling_rate: int, n_channels: int,
                 sensor_info: list, device_address: str = "",
                 chunk_size: int = 1000, phase: str = ""):
        """
        Args:
            file_path: HDF5 文件路径
            sampling_rate: 采样率 (Hz)
            n_channels: 通道数
            sensor_info: 传感器信息列表 [(port, type, name_cn), ...]
            device_address: 设备蓝牙地址
            chunk_size: 每次追加写入的块大小
            phase: 本次采集阶段（静息态/任务态/恢复态）
        """
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._sampling_rate = sampling_rate
        self._n_channels = n_channels
        self._chunk_size = chunk_size

        # 缓冲区
        self._data_buffer = []
        self._time_buffer = []
        self._total_written = 0
        self._start_time = None
        self._h5_file: Optional[h5py.File] = None
        self._is_open = False

        # 元数据
        self._meta = {
            "sampling_rate": sampling_rate,
            "n_channels": n_channels,
            "device_address": device_address,
            "start_time": datetime.now().isoformat(),
            "sensor_info": sensor_info,
            "phase": phase,
        }

    def open(self):
        """打开/创建 HDF5 文件。"""
        self._h5_file = h5py.File(str(self._file_path), "w")
        self._is_open = True

        # 创建可扩展数据集
        max_shape = (None, self._n_channels)
        self._h5_file.create_dataset(
            "raw_data", shape=(0, self._n_channels),
            maxshape=max_shape, dtype="float64",
            chunks=(self._chunk_size, self._n_channels),
            compression="gzip", compression_opts=4,
        )
        self._h5_file.create_dataset(
            "timestamps", shape=(0,),
            maxshape=(None,), dtype="float64",
            chunks=(self._chunk_size,), compression="gzip",
        )

        # 事件数据集（结构化数组）
        event_dt = np.dtype([
            ("timestamp", "f8"),
            ("abs_time", "S64"),
            ("event_type", "S32"),
            ("task_id", "S16"),
            ("description", "S128"),
            ("n_seq", "i8"),
        ])
        self._h5_file.create_dataset(
            "events", shape=(0,), maxshape=(None,),
            dtype=event_dt, chunks=(self._chunk_size,),
        )

        # 写入元数据
        for key, value in self._meta.items():
            if isinstance(value, (list, dict)):
                import json
                self._h5_file.attrs[key] = json.dumps(value, ensure_ascii=False)
            else:
                self._h5_file.attrs[key] = str(value)

        self._start_time = datetime.now()
        logger.info(f"HDF5 文件已创建: {self._file_path}")

    def add_data(self, n_seq: int, data: list):
        """添加一帧数据到缓冲区。"""
        if not self._is_open:
            return

        elapsed = (datetime.now() - self._start_time).total_seconds()
        self._data_buffer.append(data)
        self._time_buffer.append(elapsed)

        # 达到块大小时刷新写入
        if len(self._data_buffer) >= self._chunk_size:
            self._flush()

    def add_event(self, timestamp: float, abs_time: str, event_type: str,
                  task_id: str, description: str, n_seq: int = 0):
        """添加事件标记。"""
        if not self._is_open:
            return

        event_data = np.array([
            (timestamp, abs_time.encode("utf-8"),
             event_type.encode("utf-8"), task_id.encode("utf-8"),
             description.encode("utf-8"), n_seq)
        ], dtype=self._h5_file["events"].dtype)

        events_ds = self._h5_file["events"]
        old_size = events_ds.shape[0]
        events_ds.resize(old_size + 1, axis=0)
        events_ds[old_size] = event_data[0]
        self._h5_file.flush()

    def _flush(self):
        """将缓冲数据写入文件。"""
        if not self._data_buffer or not self._is_open:
            return

        data_arr = np.array(self._data_buffer, dtype="float64")
        time_arr = np.array(self._time_buffer, dtype="float64")

        raw_ds = self._h5_file["raw_data"]
        time_ds = self._h5_file["timestamps"]

        old_size = raw_ds.shape[0]
        new_size = old_size + len(data_arr)

        raw_ds.resize(new_size, axis=0)
        time_ds.resize(new_size, axis=0)
        raw_ds[old_size:] = data_arr
        time_ds[old_size:] = time_arr

        self._total_written += len(data_arr)
        self._data_buffer.clear()
        self._time_buffer.clear()
        self._h5_file.flush()

    def close(self):
        """关闭文件，刷新剩余数据。"""
        if not self._is_open:
            return

        self._flush()

        # 写入结束时间
        self._h5_file.attrs["end_time"] = datetime.now().isoformat()
        self._h5_file.attrs["total_samples"] = self._total_written
        duration = (datetime.now() - self._start_time).total_seconds()
        self._h5_file.attrs["duration_sec"] = duration

        self._h5_file.close()
        self._is_open = False
        logger.info(f"HDF5 文件已关闭: {self._file_path}, "
                    f"共 {self._total_written} 样本, {duration:.1f}s")

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def total_written(self) -> int:
        return self._total_written
