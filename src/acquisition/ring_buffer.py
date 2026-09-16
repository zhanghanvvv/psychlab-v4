"""环形缓冲区，用于实时数据缓存。

基于 numpy 数组实现，线程安全（QMutex 保护）。
支持 push（写入新数据）和 read_latest（读取最新 N 个样本）。
"""

import numpy as np
from typing import Optional
from PySide6.QtCore import QMutex, QMutexLocker


class RingBuffer:
    """多通道环形缓冲区。

    固定容量，新数据覆盖最旧数据。适合实时波形显示的滚动窗口。
    """

    def __init__(self, n_channels: int, capacity: int):
        """
        Args:
            n_channels: 通道数
            capacity: 每通道最大样本数
        """
        self._n_channels = n_channels
        self._capacity = capacity
        self._data = np.zeros((capacity, n_channels), dtype=np.float64)
        self._write_idx = 0
        self._count = 0  # 已写入的总样本数（不超过 capacity 后保持 capacity）
        self._mutex = QMutex()

    def push(self, samples: np.ndarray) -> None:
        """写入一批样本。

        Args:
            samples: shape (n_samples, n_channels) 的数组
        """
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)

        n = samples.shape[0]
        locker = QMutexLocker(self._mutex)
        for i in range(n):
            self._data[self._write_idx] = samples[i]
            self._write_idx = (self._write_idx + 1) % self._capacity
            if self._count < self._capacity:
                self._count += 1

    def push_frame(self, data: list) -> None:
        """写入单帧数据（onRawFrame 回调用）。"""
        arr = np.array(data, dtype=np.float64).reshape(1, -1)
        self.push(arr)

    def read_latest(self, n: int) -> np.ndarray:
        """读取最新的 n 个样本。

        Returns:
            shape (n, n_channels) 的数组，如果不足 n 个则返回全部
        """
        locker = QMutexLocker(self._mutex)
        actual_n = min(n, self._count)
        if actual_n == 0:
            return np.empty((0, self._n_channels))

        # 计算起始索引
        start = (self._write_idx - actual_n) % self._capacity
        if start + actual_n <= self._capacity:
            return self._data[start:start + actual_n].copy()
        else:
            # 跨越缓冲区边界，需要拼接
            part1 = self._data[start:].copy()
            part2 = self._data[:actual_n - (self._capacity - start)].copy()
            return np.vstack([part1, part2])

    def read_all(self) -> np.ndarray:
        """读取全部已存数据。"""
        return self.read_latest(self._count)

    @property
    def count(self) -> int:
        """已存样本数。"""
        locker = QMutexLocker(self._mutex)
        return self._count

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def n_channels(self) -> int:
        return self._n_channels

    def clear(self) -> None:
        """清空缓冲区。"""
        locker = QMutexLocker(self._mutex)
        self._write_idx = 0
        self._count = 0
