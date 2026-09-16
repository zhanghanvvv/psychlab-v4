"""CSV 导出器，将 HDF5 数据导出为 CSV 格式。"""

import numpy as np
import csv
from pathlib import Path
from typing import Optional

from .hdf5_reader import RecordingData
from ..utils.logger import logger


class CSVExporter:
    """将录制数据导出为 CSV 文件。"""

    @staticmethod
    def export(recording: RecordingData, file_path: str,
               sensor_info: Optional[list] = None) -> bool:
        """导出数据为 CSV。

        Args:
            recording: RecordingData 对象
            file_path: 输出 CSV 文件路径
            sensor_info: 传感器信息 [(port, type, name_cn), ...]

        Returns:
            成功返回 True
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            n_samples, n_channels = recording.raw_data.shape

            # 构建表头
            header = ["timestamp_sec"]
            if sensor_info:
                for port, stype, name_cn in sensor_info[:n_channels]:
                    header.append(f"ch{port}_{stype}")
            else:
                for i in range(n_channels):
                    header.append(f"ch{i+1}")

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(header)

                # 分块写入避免内存问题
                chunk = 10000
                for i in range(0, n_samples, chunk):
                    end = min(i + chunk, n_samples)
                    rows = np.column_stack([
                        recording.timestamps[i:end],
                        recording.raw_data[i:end]
                    ])
                    writer.writerows(rows.tolist())

            logger.info(f"CSV 导出完成: {path}, {n_samples}行")
            return True

        except Exception as e:
            logger.error(f"CSV 导出失败: {e}", exc_info=True)
            return False

    @staticmethod
    def export_events(events: list, file_path: str) -> bool:
        """导出事件标记为 CSV。"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp_sec", "abs_time", "event_type",
                    "task_id", "description", "n_seq"
                ])
                for event in events:
                    writer.writerow([
                        event.get("timestamp", 0),
                        event.get("abs_time", ""),
                        event.get("event_type", ""),
                        event.get("task_id", ""),
                        event.get("description", ""),
                        event.get("n_seq", 0),
                    ])
            logger.info(f"事件 CSV 导出完成: {path}, {len(events)}条")
            return True
        except Exception as e:
            logger.error(f"事件 CSV 导出失败: {e}")
            return False
