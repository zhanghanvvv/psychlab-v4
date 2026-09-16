"""脑电 (EEG) 信号分析。

包括：频带功率(δ/θ/α/β/γ)、功率谱密度(PSD)、频谱图。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass
from scipy import signal as scipy_signal

from ..utils.logger import logger


# EEG 频带定义 (Hz)
EEG_BANDS = {
    "Delta": (0.5, 4.0),    # δ
    "Theta": (4.0, 8.0),    # θ
    "Alpha": (8.0, 13.0),   # α
    "Beta":  (13.0, 30.0),  # β
    "Gamma": (30.0, 50.0),  # γ
}


@dataclass
class EEGResult:
    """EEG 分析结果。"""
    band_powers: dict               # {频带名: 绝对功率 (uV^2)}
    band_ratios: dict               # {频带名: 相对功率 (%) }
    total_power: float              # 总功率
    freqs: np.ndarray               # 频率数组
    psd: np.ndarray                  # 功率谱密度数组
    spectrogram: Optional[np.ndarray] = None  # 频谱图


def analyze_eeg(eeg_signal: np.ndarray, sampling_rate: int = 1000,
                 window_sec: float = 2.0) -> EEGResult:
    """分析 EEG 信号。

    Args:
        eeg_signal: EEG 原始信号 (1D)
        sampling_rate: 采样率
        window_sec: 分析窗口长度(秒)

    Returns:
        EEGResult 分析结果
    """
    try:
        # 功率谱密度 (Welch 法)
        nperseg = int(window_sec * sampling_rate)
        nperseg = min(nperseg, len(eeg_signal))
        nperseg = max(nperseg, 256)

        freqs, psd = scipy_signal.welch(
            eeg_signal, fs=sampling_rate, nperseg=nperseg
        )

        # 各频带功率
        band_powers = {}
        for band_name, (low, high) in EEG_BANDS.items():
            mask = (freqs >= low) & (freqs <= high)
            power = float(np.trapz(psd[mask], freqs[mask]))
            band_powers[band_name] = power

        total_power = float(np.trapz(psd, freqs))

        # 相对功率
        band_ratios = {}
        if total_power > 0:
            for band_name, power in band_powers.items():
                band_ratios[band_name] = (power / total_power) * 100

        # 频谱图 (短时傅里叶变换)
        nperseg_spec = min(256, len(eeg_signal))
        f_spec, t_spec, sxx = scipy_signal.spectrogram(
            eeg_signal, fs=sampling_rate, nperseg=nperseg_spec,
            noverlap=nperseg_spec // 2
        )

        result = EEGResult(
            band_powers=band_powers,
            band_ratios=band_ratios,
            total_power=total_power,
            freqs=freqs,
            psd=psd,
            spectrogram=sxx,
        )

        logger.info(
            f"EEG 分析: δ={band_powers['Delta']:.2f}, "
            f"θ={band_powers['Theta']:.2f}, "
            f"α={band_powers['Alpha']:.2f}, "
            f"β={band_powers['Beta']:.2f}, "
            f"γ={band_powers['Gamma']:.2f}"
        )
        return result

    except Exception as e:
        logger.error(f"EEG 分析异常: {e}", exc_info=True)
        return EEGResult(
            band_powers={k: 0 for k in EEG_BANDS},
            band_ratios={k: 0 for k in EEG_BANDS},
            total_power=0,
            freqs=np.array([]),
            psd=np.array([]),
        )


def compute_alpha_theta_ratio(eeg_signal: np.ndarray,
                              sampling_rate: int = 1000) -> float:
    """计算 Alpha/Theta 比值（注意力/放松指标）。"""
    result = analyze_eeg(eeg_signal, sampling_rate)
    alpha = result.band_powers.get("Alpha", 0)
    theta = result.band_powers.get("Theta", 0)
    return alpha / theta if theta > 0 else 0
