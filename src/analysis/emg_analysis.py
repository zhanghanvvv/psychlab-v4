"""肌电 (EMG) 信号分析。

包括：RMS 振幅、平均频率(MNF)、中值频率(MDF)、肌肉疲劳分析。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass
from scipy import signal as scipy_signal

from ..utils.logger import logger


@dataclass
class EMGResult:
    """EMG 分析结果。"""
    rms: float                     # RMS 振幅
    mean_freq: float               # 平均频率 (Hz)
    median_freq: float             # 中值频率 (Hz)
    max_amplitude: float           # 最大振幅
    fatigue_index: Optional[float] = None  # 疲劳指数(中值频率斜率)
    envelope: Optional[np.ndarray] = None   # 包络曲线


def analyze_emg(emg_signal: np.ndarray, sampling_rate: int = 1000,
                window_sec: float = 0.5) -> EMGResult:
    """分析 EMG 信号。

    Args:
        emg_signal: EMG 原始信号 (1D)
        sampling_rate: 采样率
        window_sec: RMS 窗口长度(秒)

    Returns:
        EMGResult 分析结果
    """
    try:
        # RMS
        rms = np.sqrt(np.mean(emg_signal ** 2))

        # 包络（RMS 滑动窗口）
        window = int(window_sec * sampling_rate)
        if window > 0 and len(emg_signal) > window:
            envelope = np.sqrt(
                np.convolve(emg_signal ** 2, np.ones(window) / window, mode="same")
            )
        else:
            envelope = np.array([rms] * len(emg_signal))

        # 频域分析
        n = len(emg_signal)
        freqs, psd = scipy_signal.welch(
            emg_signal, fs=sampling_rate, nperseg=min(n, 2048)
        )

        if psd.sum() > 0:
            # 平均频率
            mean_freq = np.sum(freqs * psd) / np.sum(psd)

            # 中值频率
            cumsum = np.cumsum(psd)
            total = cumsum[-1]
            median_freq = freqs[np.searchsorted(cumsum, total / 2)]
        else:
            mean_freq = 0.0
            median_freq = 0.0

        max_amp = np.max(np.abs(emg_signal))

        result = EMGResult(
            rms=float(rms),
            mean_freq=float(mean_freq),
            median_freq=float(median_freq),
            max_amplitude=float(max_amp),
            envelope=envelope,
        )

        logger.info(f"EMG 分析: RMS={rms:.4f}, MNF={mean_freq:.1f}Hz, "
                    f"MDF={median_freq:.1f}Hz")
        return result

    except Exception as e:
        logger.error(f"EMG 分析异常: {e}", exc_info=True)
        return EMGResult(rms=0, mean_freq=0, median_freq=0, max_amplitude=0)


def compute_fatigue_index(emg_signal: np.ndarray,
                           sampling_rate: int = 1000,
                           segment_sec: float = 10) -> Optional[float]:
    """计算肌肉疲劳指数（中值频率随时间变化的斜率）。

    负斜率表示疲劳（中值频率下降）。

    Args:
        emg_signal: EMG 信号
        sampling_rate: 采样率
        segment_sec: 分段时长(秒)

    Returns:
        疲劳指数（斜率），None 表示无法计算
    """
    segment_len = int(segment_sec * sampling_rate)
    n_segments = len(emg_signal) // segment_len

    if n_segments < 3:
        return None

    mdf_values = []
    for i in range(n_segments):
        segment = emg_signal[i * segment_len:(i + 1) * segment_len]
        freqs, psd = scipy_signal.welch(
            segment, fs=sampling_rate, nperseg=min(len(segment), 2048)
        )
        if psd.sum() > 0:
            cumsum = np.cumsum(psd)
            mdf = freqs[np.searchsorted(cumsum, cumsum[-1] / 2)]
            mdf_values.append(mdf)

    if len(mdf_values) < 3:
        return None

    # 线性回归斜率
    x = np.arange(len(mdf_values))
    coeffs = np.polyfit(x, mdf_values, 1)
    fatigue_index = float(coeffs[0])

    logger.info(f"疲劳指数(MDF斜率): {fatigue_index:.4f} Hz/segment")
    return fatigue_index
