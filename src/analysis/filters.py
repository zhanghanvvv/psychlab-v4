"""信号滤波器。

提供带通滤波、陷波滤波和移动平均，基于 scipy.signal。
按信号类型提供默认滤波参数。
"""

import numpy as np
from scipy import signal
from typing import Optional, Tuple


def bandpass_filter(data: np.ndarray, lowcut: Optional[float],
                     highcut: Optional[float], fs: float,
                     order: int = 4) -> np.ndarray:
    """Butterworth 带通滤波。

    Args:
        data: 输入信号 (1D)
        lowcut: 低频截止 (Hz)，None=不过滤低频
        highcut: 高频截止 (Hz)，None=不过滤高频
        fs: 采样率
        order: 滤波器阶数

    Returns:
        滤波后的信号
    """
    if lowcut is None and highcut is None:
        return data.copy()

    nyq = fs / 2.0

    # 防止归一化频率越界（必须 0 < Wn < 1）
    # 并限制最小值 0.001 以避免窄带通数值溢出
    def _norm(freq: Optional[float]) -> Optional[float]:
        if freq is None:
            return None
        if freq <= 0:
            return 1e-3
        if freq >= nyq:
            return 0.999
        v = freq / nyq
        return max(v, 1e-3)

    low_n = _norm(lowcut)
    high_n = _norm(highcut)

    if low_n is not None and high_n is not None:
        # 带通过窄或反向则降级为低通（避免数值不稳定）
        # 经验阈值 0.01：低于此带宽 sosfiltfilt 仍可能溢出
        if low_n >= high_n or (high_n - low_n) < 0.01:
            sos = signal.butter(order, high_n, btype="low", output="sos")
        else:
            sos = signal.butter(order, [low_n, high_n], btype="band", output="sos")
    elif low_n is not None:
        # 高通
        sos = signal.butter(order, low_n, btype="high", output="sos")
    elif high_n is not None:
        # 低通
        sos = signal.butter(order, high_n, btype="low", output="sos")
    else:
        return data.copy()

    # 使用 sos 二阶节形式，数值更稳定（避免窄带通滤波器溢出）
    try:
        return signal.sosfiltfilt(sos, data)
    except ValueError:
        # 极端情况下 sosfiltfilt 失败，回退无滤波
        return data.copy()


def notch_filter(data: np.ndarray, freq: float, fs: float,
                  quality: float = 30.0) -> np.ndarray:
    """陷波滤波（滤除特定频率，如50Hz工频）。

    Args:
        data: 输入信号
        freq: 陷波频率 (Hz)
        fs: 采样率
        quality: 品质因子（越大滤波带越窄）

    Returns:
        滤波后的信号
    """
    if freq is None or freq <= 0:
        return data.copy()
    nyq = fs / 2.0
    if freq >= nyq:
        return data.copy()
    w0 = freq / nyq
    # iirnotch 不支持 sos 输出，使用 tf2sos 转换以保证稳定性
    b, a = signal.iirnotch(w0, quality)
    sos = signal.tf2sos(b, a)
    return signal.sosfiltfilt(sos, data)


def moving_average(data: np.ndarray, window: int) -> np.ndarray:
    """移动平均平滑。"""
    if window <= 1:
        return data.copy()
    kernel = np.ones(window) / window
    return np.convolve(data, kernel, mode="same")


def apply_sensor_filter(data: np.ndarray, sensor_type: str,
                        fs: float) -> np.ndarray:
    """根据传感器类型应用默认滤波。

    Args:
        data: 原始信号
        sensor_type: 传感器类型 (ECG/EMG/EEG/EDA/BVP/RESP/EOG/EGG)
        fs: 采样率

    Returns:
        滤波后信号
    """
    from ..device.sensor_types import get_sensor_meta

    meta = get_sensor_meta(sensor_type)
    result = data.copy()

    if meta.filter_low or meta.filter_high:
        result = bandpass_filter(result, meta.filter_low, meta.filter_high, fs)

    if meta.notch_freq:
        result = notch_filter(result, meta.notch_freq, fs)

    return result
