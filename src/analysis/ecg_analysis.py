"""心电 (ECG) 信号分析。

包括：R波检测、心率计算、HRV时域与频域分析。
使用 neurokit2 进行 R 波检测和 HRV 计算。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass

from ..utils.logger import logger


@dataclass
class ECGResult:
    """ECG 分析结果。"""
    heart_rate: float              # 平均心率 (bpm)
    rr_intervals: np.ndarray       # RR 间期数组 (秒)
    n_beats: int                   # 心搏数
    # HRV 时域
    sdnn: Optional[float] = None   # RR间期标准差 (ms)
    rmssd: Optional[float] = None  # 连续RR间期差值均方根 (ms)
    pnn50: Optional[float] = None  # NN50 占比 (%)
    mean_rr: Optional[float] = None  # 平均RR间期 (ms)
    # HRV 频域
    lf_power: Optional[float] = None  # 低频功率 (ms^2)
    hf_power: Optional[float] = None  # 高频功率 (ms^2)
    lf_hf_ratio: Optional[float] = None  # LF/HF 比值
    peaks_idx: Optional[np.ndarray] = None  # R波索引


def analyze_ecg(ecg_signal: np.ndarray, sampling_rate: int = 1000) -> ECGResult:
    """分析 ECG 信号。

    Args:
        ecg_signal: ECG 原始信号 (1D)
        sampling_rate: 采样率

    Returns:
        ECGResult 分析结果
    """
    try:
        import neurokit2 as nk
    except ImportError:
        logger.warning("neurokit2 未安装，无法进行 ECG 分析")
        return ECGResult(heart_rate=0, rr_intervals=np.array([]), n_beats=0)

    try:
        # 清理信号
        ecg_cleaned = nk.ecg_clean(ecg_signal, sampling_rate=sampling_rate)

        # 检测 R 波
        _, info = nk.ecg_peaks(
            ecg_cleaned, sampling_rate=sampling_rate,
            method="neurokit", correct_artifacts=True
        )
        peaks = info.get("ECG_R_Peaks", np.array([]))

        if len(peaks) < 2:
            logger.warning("未检测到足够的 R 波")
            return ECGResult(
                heart_rate=0, rr_intervals=np.array([]), n_beats=len(peaks)
            )

        # 计算 RR 间期
        rr_intervals = np.diff(peaks) / sampling_rate  # 秒
        mean_hr = 60.0 / np.mean(rr_intervals) if np.mean(rr_intervals) > 0 else 0

        result = ECGResult(
            heart_rate=mean_hr,
            rr_intervals=rr_intervals,
            n_beats=len(peaks),
            peaks_idx=peaks,
        )

        # HRV 时域分析
        hrv_time = nk.hrv_time(info, sampling_rate=sampling_rate, show=False)
        if hrv_time is not None and not hrv_time.empty:
            result.sdnn = float(hrv_time["HRV_SDNN"].iloc[0]) if "HRV_SDNN" in hrv_time.columns else None
            result.rmssd = float(hrv_time["HRV_RMSSD"].iloc[0]) if "HRV_RMSSD" in hrv_time.columns else None
            result.pnn50 = float(hrv_time["HRV_pNN50"].iloc[0]) if "HRV_pNN50" in hrv_time.columns else None
            result.mean_rr = float(hrv_time["HRV_MeanNN"].iloc[0]) if "HRV_MeanNN" in hrv_time.columns else None

        # HRV 频域分析
        try:
            hrv_freq = nk.hrv_frequency(info, sampling_rate=sampling_rate, show=False)
            if hrv_freq is not None and not hrv_freq.empty:
                result.lf_power = float(hrv_freq["HRV_LF"].iloc[0]) if "HRV_LF" in hrv_freq.columns else None
                result.hf_power = float(hrv_freq["HRV_HF"].iloc[0]) if "HRV_HF" in hrv_freq.columns else None
                if result.lf_power and result.hf_power and result.hf_power > 0:
                    result.lf_hf_ratio = result.lf_power / result.hf_power
        except Exception as e:
            logger.warning(f"HRV 频域分析失败: {e}")

        logger.info(f"ECG 分析完成: HR={mean_hr:.1f}bpm, "
                    f"SDNN={result.sdnn}, RMSSD={result.rmssd}")
        return result

    except Exception as e:
        logger.error(f"ECG 分析异常: {e}", exc_info=True)
        return ECGResult(heart_rate=0, rr_intervals=np.array([]), n_beats=0)


def compute_instant_hr(rr_intervals: np.ndarray) -> np.ndarray:
    """计算瞬时心率序列。"""
    if len(rr_intervals) == 0:
        return np.array([])
    return 60.0 / rr_intervals
