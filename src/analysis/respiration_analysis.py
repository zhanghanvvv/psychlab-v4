"""呼吸 (RESP) 信号分析。

包括：呼吸频率、吸呼比、幅度变异。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass
from scipy import signal as scipy_signal

from ..utils.logger import logger


@dataclass
class RespirationResult:
    """呼吸分析结果。"""
    breathing_rate: float          # 平均呼吸频率 (次/分)
    mean_amplitude: float          # 平均幅度
    ie_ratio: Optional[float] = None  # 吸呼比 (吸气时间/呼气时间)
    peaks: Optional[np.ndarray] = None  # 吸气峰值索引
    troughs: Optional[np.ndarray] = None  # 呼气谷值索引
    rate_series: Optional[np.ndarray] = None  # 瞬时呼吸频率序列


def analyze_respiration(resp_signal: np.ndarray,
                          sampling_rate: int = 1000) -> RespirationResult:
    """分析呼吸信号。

    Args:
        resp_signal: 呼吸原始信号 (1D)
        sampling_rate: 采样率

    Returns:
        RespirationResult 分析结果
    """
    try:
        # 带通滤波 (0.1-2 Hz)，使用 sos 二阶节形式避免窄带通数值溢出
        nyq = sampling_rate / 2
        low = max(0.1 / nyq, 1e-3)
        high = min(2.0 / nyq, 0.999)
        if high - low < 0.01:
            # 带通过窄，降级为低通
            sos = scipy_signal.butter(4, high, btype="low", output="sos")
        else:
            sos = scipy_signal.butter(4, [low, high], btype="band", output="sos")
        filtered = scipy_signal.sosfiltfilt(sos, resp_signal)

        # 检测峰值（吸气）
        min_distance = int(1.5 * sampling_rate)  # 最小1.5秒间隔
        peaks, _ = scipy_signal.find_peaks(
            filtered, distance=min_distance,
            height=np.std(filtered) * 0.5
        )

        # 检测谷值（呼气）
        troughs, _ = scipy_signal.find_peaks(
            -filtered, distance=min_distance,
            height=-np.std(filtered) * 0.5
        )

        # 呼吸频率
        if len(peaks) >= 2:
            peak_intervals = np.diff(peaks) / sampling_rate  # 秒
            mean_period = np.mean(peak_intervals)
            breathing_rate = 60.0 / mean_period if mean_period > 0 else 0
        else:
            breathing_rate = 0.0

        # 幅度
        amplitude = float(np.ptp(filtered))

        # 吸呼比
        ie_ratio = None
        if len(peaks) > 0 and len(troughs) > 0:
            # 取呼吸周期中的吸气和呼气时间
            ratios = []
            for i in range(min(len(peaks), len(troughs)) - 1):
                # 吸气: 从谷到峰
                inspiration = (peaks[i] - troughs[i]) / sampling_rate
                # 呼气: 从峰到下一谷
                if i + 1 < len(troughs):
                    expiration = (troughs[i + 1] - peaks[i]) / sampling_rate
                    if expiration > 0:
                        ratios.append(inspiration / expiration)
            if ratios:
                ie_ratio = float(np.mean(ratios))

        # 瞬时呼吸频率
        rate_series = None
        if len(peaks) >= 3:
            intervals = np.diff(peaks) / sampling_rate
            rate_series = 60.0 / intervals

        result = RespirationResult(
            breathing_rate=float(breathing_rate),
            mean_amplitude=amplitude,
            ie_ratio=ie_ratio,
            peaks=peaks,
            troughs=troughs,
            rate_series=rate_series,
        )

        logger.info(f"呼吸分析: {breathing_rate:.1f}次/分, "
                    f"幅度={amplitude:.2f}, I/E={ie_ratio}")
        return result

    except Exception as e:
        logger.error(f"呼吸分析异常: {e}", exc_info=True)
        return RespirationResult(
            breathing_rate=0, mean_amplitude=0
        )
