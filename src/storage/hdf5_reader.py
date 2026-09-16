"""HDF5 数据读取器，用于离线分析加载。"""

import numpy as np
import h5py
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from ..utils.logger import logger


@dataclass
class RecordingData:
    """已录制数据。"""
    raw_data: np.ndarray           # (n_samples, n_channels)
    timestamps: np.ndarray         # (n_samples,)
    events: list                   # 事件列表 [{timestamp, ...}]
    sampling_rate: int
    n_channels: int
    duration_sec: float
    start_time: str
    device_address: str
    sensor_info: list              # [(port, type, name_cn), ...]
    phase: str = ""                # 采集阶段（静息态/任务态/恢复态）


class HDF5Reader:
    """HDF5 文件读取器。"""

    @staticmethod
    def load(file_path: str) -> Optional[RecordingData]:
        """加载 HDF5 文件。

        Args:
            file_path: HDF5 文件路径

        Returns:
            RecordingData 对象，加载失败返回 None
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        try:
            with h5py.File(str(path), "r") as f:
                raw_data = f["raw_data"][:] if "raw_data" in f else np.empty((0, 0))
                timestamps = f["timestamps"][:] if "timestamps" in f else np.empty(0)

                # 读取事件
                events = []
                if "events" in f and f["events"].shape[0] > 0:
                    events_arr = f["events"][:]
                    for row in events_arr:
                        events.append({
                            "timestamp": float(row["timestamp"]),
                            "abs_time": row["abs_time"].decode("utf-8") if isinstance(row["abs_time"], bytes) else str(row["abs_time"]),
                            "event_type": row["event_type"].decode("utf-8") if isinstance(row["event_type"], bytes) else str(row["event_type"]),
                            "task_id": row["task_id"].decode("utf-8") if isinstance(row["task_id"], bytes) else str(row["task_id"]),
                            "description": row["description"].decode("utf-8") if isinstance(row["description"], bytes) else str(row["description"]),
                            "n_seq": int(row["n_seq"]),
                        })

                # 读取元数据
                attrs = dict(f.attrs)
                sampling_rate = int(attrs.get("sampling_rate", "1"))
                n_channels = int(attrs.get("n_channels", str(raw_data.shape[1] if raw_data.ndim > 1 else 1)))
                duration_sec = float(attrs.get("duration_sec", "0"))
                start_time = attrs.get("start_time", "").decode("utf-8") if isinstance(attrs.get("start_time"), bytes) else str(attrs.get("start_time", ""))
                device_address = attrs.get("device_address", "").decode("utf-8") if isinstance(attrs.get("device_address"), bytes) else str(attrs.get("device_address", ""))

                # 传感器信息
                sensor_info_json = attrs.get("sensor_info", "[]")
                if isinstance(sensor_info_json, bytes):
                    sensor_info_json = sensor_info_json.decode("utf-8")
                try:
                    sensor_info = json.loads(sensor_info_json)
                except (json.JSONDecodeError, TypeError):
                    sensor_info = []

                # 采集阶段
                phase_raw = attrs.get("phase", "")
                if isinstance(phase_raw, bytes):
                    phase_raw = phase_raw.decode("utf-8")
                phase = str(phase_raw) if phase_raw else ""

                logger.info(f"已加载: {path.name}, {raw_data.shape[0]}样本, "
                           f"{n_channels}通道, {duration_sec:.1f}s, phase={phase}")

                return RecordingData(
                    raw_data=raw_data,
                    timestamps=timestamps,
                    events=events,
                    sampling_rate=sampling_rate,
                    n_channels=n_channels,
                    duration_sec=duration_sec,
                    start_time=start_time,
                    device_address=device_address,
                    sensor_info=sensor_info,
                    phase=phase,
                )

        except Exception as e:
            logger.error(f"加载 HDF5 失败: {e}", exc_info=True)
            return None
