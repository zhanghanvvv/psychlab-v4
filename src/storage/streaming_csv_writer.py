"""流式 CSV 写入器。

参考 SYNAPSE-DRIVE 的实现：使用独立写入线程 + 队列，
每批数据写入后 flush，确保10小时持续采集时数据不丢失。

与 HDF5Writer 互补：HDF5 适合离线分析，CSV 适合通用查看和快速处理。
"""

import csv
import time
import queue
import threading
from pathlib import Path
from typing import Optional, List

from ..utils.logger import logger


class StreamingCSVWriter:
    """流式 CSV 写入器。

    用法:
        writer = StreamingCSVWriter("data/physiology.csv", ["timestamp", "ch1", "ch2"])
        writer.start()
        writer.write_row([1.0, 0.5, 0.3])
        ...
        writer.stop()
    """

    def __init__(self, file_path: str, header: List[str],
                 queue_maxsize: int = 50000,
                 flush_interval: float = 1.0):
        """
        Args:
            file_path: CSV 文件路径
            header: 表头列表
            queue_maxsize: 写入队列最大容量
            flush_interval: 自动flush间隔(秒)
        """
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._header = header
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._flush_interval = flush_interval

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._file = None
        self._csv_writer = None
        self._rows_written = 0
        self._last_flush_time = 0

    def start(self):
        """启动写入线程。"""
        self._stop_event.clear()

        # 创建文件并写入表头
        file_exists = self._file_path.exists()
        self._file = open(self._file_path, "a", newline="", encoding="utf-8-sig")
        self._csv_writer = csv.writer(self._file)
        if not file_exists:
            self._csv_writer.writerow(self._header)
            self._file.flush()

        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()
        logger.info(f"流式 CSV 写入已启动: {self._file_path}")

    def write_row(self, row: list):
        """写入一行数据（非阻塞，放入队列）。"""
        if self._stop_event.is_set():
            return
        try:
            self._queue.put_nowait(row)
        except queue.Full:
            # 队列满时丢弃最旧数据，避免阻塞采集线程
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(row)
            except queue.Empty:
                pass

    def write_rows(self, rows: List[list]):
        """批量写入多行。"""
        for row in rows:
            self.write_row(row)

    def stop(self):
        """停止写入，刷新剩余数据。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

        # 写入队列中剩余数据
        self._flush_remaining()

        if self._file:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            self._file = None

        logger.info(f"流式 CSV 写入已停止: {self._file_path}, "
                    f"共 {self._rows_written} 行")

    def _write_loop(self):
        """写入线程主循环。"""
        while not self._stop_event.is_set():
            try:
                # 从队列获取数据（带超时，便于检查停止信号）
                row = self._queue.get(timeout=0.1)
                self._csv_writer.writerow(row)
                self._rows_written += 1

                # 定期 flush
                now = time.time()
                if now - self._last_flush_time >= self._flush_interval:
                    self._file.flush()
                    self._last_flush_time = now

            except queue.Empty:
                # 队列为空时检查是否需要 flush
                now = time.time()
                if now - self._last_flush_time >= self._flush_interval:
                    try:
                        self._file.flush()
                        self._last_flush_time = now
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"CSV 写入错误: {e}", exc_info=True)

    def _flush_remaining(self):
        """写入队列中剩余的所有数据。"""
        if self._csv_writer is None:
            return
        try:
            while not self._queue.empty():
                row = self._queue.get_nowait()
                self._csv_writer.writerow(row)
                self._rows_written += 1
            self._file.flush()
        except Exception as e:
            logger.error(f"刷新剩余数据失败: {e}")

    @property
    def rows_written(self) -> int:
        return self._rows_written

    @property
    def file_path(self) -> Path:
        return self._file_path
