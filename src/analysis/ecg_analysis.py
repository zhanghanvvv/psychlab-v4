"""心电 (ECG) 信号分析。

包括：R波检测、心率计算、HRV 完整 20 项指标分析。
使用 neurokit2 进行 R 波检测和 HRV 计算（参考 ESC/NASPE 标准）。
"""

import numpy as np
from typing import Optional
from dataclasses import dataclass

from ..utils.logger import logger


@dataclass
class ECGResult:
    """ECG 分析结果（含 Top 20 HRV 指标）。

    指标分类（参考 ESC/NASPE 标准）：
      时域 1-8: SDNN/RMSSD/pNN50/SDSD/SDANN/SDNNI/MeanNN/pNN20
      频域 9-14: TP/HF/LF/LF_HF/VLF/ULF
      非线性 15-20: SD1/SD2/SD1SD2/SampEn/ApEn/DFA_alpha1
    短时记录（<5min）时 SDANN/SDNNI/ULF 等长时指标为 None。
    """
    heart_rate: float                # 平均心率 (bpm)
    rr_intervals: np.ndarray         # RR 间期数组 (秒)
    n_beats: int                     # 心搏数
    peaks_idx: Optional[np.ndarray] = None  # R波索引

    # ── 时域 1-8 ──
    mean_nn: Optional[float] = None     # 1. MeanNN 全部NN间期平均值 (ms)
    sdnn: Optional[float] = None        # 2. SDNN 全部NN间期标准差 (ms)
    rmssd: Optional[float] = None       # 3. RMSSD 相邻NN差值均方根 (ms)
    pnn50: Optional[float] = None       # 4. pNN50 相邻NN差>50ms占比 (%)
    sdsd: Optional[float] = None        # 5. SDSD 相邻NN差值标准差 (ms)
    sdann: Optional[float] = None       # 6. SDANN 每5min片段NN均值标准差 (ms) [需长时]
    sdnni: Optional[float] = None       # 7. SDNNI 每5min片段SDNN均值 (ms) [需长时]
    pnn20: Optional[float] = None       # 8. pNN20 相邻NN差>20ms占比 (%)

    # ── 频域 9-14 ──
    tp: Optional[float] = None          # 9. TP 总功率 (ms^2)
    hf: Optional[float] = None           # 10. HF 高频0.15-0.4Hz (ms^2)
    lf: Optional[float] = None           # 11. LF 低频0.04-0.15Hz (ms^2)
    lf_hf_ratio: Optional[float] = None  # 12. LF/HF 比值 (无量纲)
    vlf: Optional[float] = None          # 13. VLF 极低频0.0033-0.04Hz (ms^2)
    ulf: Optional[float] = None          # 14. ULF 超低频<0.0033Hz (ms^2) [需长时]

    # ── 非线性 15-20 ──
    sd1: Optional[float] = None          # 15. SD1 Poincare短时波动 (ms)
    sd2: Optional[float] = None          # 16. SD2 Poincare长期波动 (ms)
    sd1sd2: Optional[float] = None       # 17. SD1/SD2 比值 (无量纲)
    sampen: Optional[float] = None       # 18. SampEn 样本熵 (无量纲)
    apen: Optional[float] = None         # 19. ApEn 近似熵 (无量纲)
    dfa_alpha1: Optional[float] = None   # 20. DFA α1 短程标度指数 (无量纲)


def analyze_ecg(ecg_signal: np.ndarray, sampling_rate: int = 1000) -> ECGResult:
    """分析 ECG 信号（含 Top 20 HRV 指标）。

    Args:
        ecg_signal: ECG 原始信号 (1D)，建议先标定为 mV
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

        # 工具函数：安全读取 neurokit2 DataFrame 字段
        def _get(df, key):
            if df is None or df.empty or key not in df.columns:
                return None
            v = df[key].iloc[0]
            try:
                v = float(v)
                if np.isnan(v) or np.isinf(v):
                    return None
                return v
            except (TypeError, ValueError):
                return None

        # ── 时域分析（1-8）──
        # 注意：neurokit2 >=0.2.x 将 SDANN/SDNNI 按片段长度拆成 SDANN1/SDANN2/SDANN5
        # （分别对应 1min/2min/5min 片段），需要做多候选回退
        def _get_sd_ann(df):
            for col in ("HRV_SDANN5", "HRV_SDANN2", "HRV_SDANN1", "HRV_SDANN"):
                v = _get(df, col)
                if v is not None:
                    return v
            return None

        def _get_sd_nni(df):
            for col in ("HRV_SDNNI5", "HRV_SDNNI2", "HRV_SDNNI1", "HRV_SDNNI"):
                v = _get(df, col)
                if v is not None:
                    return v
            return None

        try:
            hrv_time = nk.hrv_time(info, sampling_rate=sampling_rate, show=False)
            result.mean_nn  = _get(hrv_time, "HRV_MeanNN")
            result.sdnn     = _get(hrv_time, "HRV_SDNN")
            result.rmssd    = _get(hrv_time, "HRV_RMSSD")
            result.pnn50    = _get(hrv_time, "HRV_pNN50")
            result.sdsd     = _get(hrv_time, "HRV_SDSD")
            result.sdann    = _get_sd_ann(hrv_time)
            result.sdnni    = _get_sd_nni(hrv_time)
            result.pnn20    = _get(hrv_time, "HRV_pNN20")
        except Exception as e:
            logger.warning(f"HRV 时域分析失败: {e}")

        # ── 频域分析（9-14）──
        try:
            hrv_freq = nk.hrv_frequency(info, sampling_rate=sampling_rate, show=False)
            result.tp  = _get(hrv_freq, "HRV_TP")
            result.hf  = _get(hrv_freq, "HRV_HF")
            result.lf  = _get(hrv_freq, "HRV_LF")
            result.vlf = _get(hrv_freq, "HRV_VLF")
            result.ulf = _get(hrv_freq, "HRV_ULF")
            lf_v = result.lf
            hf_v = result.hf
            if lf_v is not None and hf_v is not None and hf_v > 0:
                result.lf_hf_ratio = lf_v / hf_v
            else:
                # neurokit2 可能直接给 HRV_LFHF 列
                result.lf_hf_ratio = _get(hrv_freq, "HRV_LFHF")
        except Exception as e:
            logger.warning(f"HRV 频域分析失败: {e}")

        # ── 非线性分析（15-20）──
        try:
            hrv_nl = nk.hrv_nonlinear(info, sampling_rate=sampling_rate, show=False)
            result.sd1         = _get(hrv_nl, "HRV_SD1")
            result.sd2         = _get(hrv_nl, "HRV_SD2")
            result.sd1sd2      = _get(hrv_nl, "HRV_SD1SD2")
            result.sampen      = _get(hrv_nl, "HRV_SampEn")
            result.apen        = _get(hrv_nl, "HRV_ApEn")
            result.dfa_alpha1  = _get(hrv_nl, "HRV_DFA_alpha1")
        except Exception as e:
            logger.warning(f"HRV 非线性分析失败: {e}")

        logger.info(
            f"ECG 分析完成: HR={mean_hr:.1f}bpm, "
            f"SDNN={result.sdnn}, RMSSD={result.rmssd}, "
            f"LF/HF={result.lf_hf_ratio}, SD1={result.sd1}"
        )
        return result

    except Exception as e:
        logger.error(f"ECG 分析异常: {e}", exc_info=True)
        return ECGResult(heart_rate=0, rr_intervals=np.array([]), n_beats=0)


def compute_instant_hr(rr_intervals: np.ndarray) -> np.ndarray:
    """计算瞬时心率序列。"""
    if len(rr_intervals) == 0:
        return np.array([])
    return 60.0 / rr_intervals
