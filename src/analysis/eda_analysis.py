"""皮电 (EDA) 信号分析。

包括：SCL(皮电水平)与SCR(皮电反应)分离、SCR事件检测。
使用 neurokit2 进行 EDA 处理。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass

from ..utils.logger import logger


@dataclass
class EDAResult:
    """EDA 分析结果。"""
    mean_scl: float                 # 平均 SCL (uS)
    scl_trend: np.ndarray           # SCL 趋势曲线
    n_scr: int                      # SCR 事件数
    scr_amplitudes: np.ndarray      # SCR 振幅列表 (uS)
    scr_onsets: np.ndarray           # SCR 起始时间 (秒)
    scr_recovery: np.ndarray        # SCR 恢复时间 (秒)


def analyze_eda(eda_signal: np.ndarray, sampling_rate: int = 1000) -> EDAResult:
    """分析 EDA 信号。

    Args:
        eda_signal: EDA 原始信号 (1D)
        sampling_rate: 采样率

    Returns:
        EDAResult 分析结果
    """
    try:
        import neurokit2 as nk
    except ImportError:
        logger.warning("neurokit2 未安装，使用简化分析")
        return _simple_eda_analysis(eda_signal, sampling_rate)

    try:
        # 清理和处理
        signals, info = nk.eda_process(
            eda_signal, sampling_rate=sampling_rate
        )

        # SCL (皮电水平)
        scl = signals.get("EDA_Tonic", eda_signal)
        mean_scl = float(np.mean(scl))

        # SCR (皮电反应) 事件
        scr_onsets = info.get("SCR_Onsets", np.array([]))
        scr_peaks = info.get("SCR_Peaks", np.array([]))
        scr_amplitude = info.get("SCR_Amplitude", np.array([]))

        n_scr = len(scr_peaks)
        amplitudes = np.array(scr_amplitude) if len(scr_amplitude) > 0 else np.array([])
        onsets = np.array(scr_onsets) / sampling_rate if len(scr_onsets) > 0 else np.array([])

        # 恢复时间
        recovery = info.get("SCR_Recovery", np.array([]))
        recovery_times = np.array(recovery) / sampling_rate if len(recovery) > 0 else np.array([])

        result = EDAResult(
            mean_scl=mean_scl,
            scl_trend=np.array(scl),
            n_scr=n_scr,
            scr_amplitudes=amplitudes,
            scr_onsets=onsets,
            scr_recovery=recovery_times,
        )

        logger.info(f"EDA 分析: SCL={mean_scl:.2f}uS, SCR事件={n_scr}")
        return result

    except Exception as e:
        logger.warning(f"neurokit2 EDA 分析失败，使用简化分析: {e}")
        return _simple_eda_analysis(eda_signal, sampling_rate)


def _simple_eda_analysis(eda_signal: np.ndarray,
                          sampling_rate: int) -> EDAResult:
    """不依赖 neurokit2 的简化 EDA 分析。"""
    # SCL: 低通滤波后的基线
    from scipy.signal import butter, filtfilt
    nyq = sampling_rate / 2
    cutoff = min(0.05 / nyq, 0.99)
    b, a = butter(4, cutoff, btype="low")
    scl = filtfilt(b, a, eda_signal) if len(eda_signal) > 100 else eda_signal

    # SCR: 去除基线后的信号
    scr_signal = eda_signal - scl
    threshold = np.std(scr_signal) * 0.5

    # 简单阈值检测 SCR 峰
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(scr_signal, height=threshold, distance=int(sampling_rate * 0.5))

    amplitudes = scr_signal[peaks] if len(peaks) > 0 else np.array([])
    onsets = peaks / sampling_rate if len(peaks) > 0 else np.array([])

    return EDAResult(
        mean_scl=float(np.mean(scl)),
        scl_trend=np.array(scl),
        n_scr=len(peaks),
        scr_amplitudes=amplitudes,
        scr_onsets=onsets,
        scr_recovery=np.array([]),
    )
