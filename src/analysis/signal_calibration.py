"""ADC 原始值 → 物理量转换。

biosignalsplux LSL 流发送的是 ADC 原始整数值（如 16 位传感器
发送 0-65535 范围的值），分析前需要按传感器规格转换为物理量
(mV / μV / μS / ℃ / % 等)。

采用直接线性映射：
    physical = raw * scale + bias
其中 scale 和 bias 由传感器量程和 ADC 分辨率决定。

举例：
- ECG 双极性 ±1.5mV，16 位 ADC：
    scale = 3.0 mV / 65535 ≈ 4.578e-5 mV/count
    bias  = -1.5 mV  (raw=0 时输出 -1.5mV；ADC 中心 32768 输出 0)
- TEMP 量程 20-40℃，16 位 ADC：
    scale = 20.0 ℃ / 65535 ≈ 3.052e-4 ℃/count
    bias  = 20.0 ℃
"""

import numpy as np
from typing import Optional

from ..device.sensor_types import get_sensor_meta
from ..utils.logger import logger


# ── 传感器线性标定参数表 ──
# 每项: (scale, bias, unit)
#   physical = raw * scale + bias
# scale/bias 的单位即 unit 字段（与 SENSOR_META.unit 一致）
CALIB_TABLE: dict[str, tuple[float, float, str]] = {
    # ── 生物电类（双极性，ADC 中心 32768 输出 0）──
    # ECG/EMG 量程 ±1.5 mV
    "ECG":  (3.0 / 65535.0, -1.5,           "mV"),
    "EMG":  (3.0 / 65535.0, -1.5,           "mV"),
    # EEG 量程 ±100 μV（高增益）
    "EEG":  (200.0 / 65535.0, -100.0,       "uV"),
    "EOG":  (3.0 / 65535.0, -1.5,           "mV"),
    "EGG":  (3.0 / 65535.0, -1.5,           "mV"),
    # ERG 量程 ±50 μV
    "ERG":  (100.0 / 65535.0, -50.0,        "uV"),

    # ── 阻抗/电导类 ──
    # EDA 量程 0-20 μS
    "EDA":  (20.0 / 65535.0, 0.0,           "uS"),
    # GSR 量程 0-500 kΩ
    "GSR":  (500.0 / 65535.0, 0.0,          "kOhm"),

    # ── 心血管与血氧类 ──
    # BVP/PPG 双极性 ±1 mV
    "BVP":  (2.0 / 65535.0, -1.0,           "mV"),
    "PPG":  (2.0 / 65535.0, -1.0,           "mV"),
    # 血氧 80-100 %
    "OXIMETER": (20.0 / 65535.0, 80.0,      "%"),
    "SpO2":     (20.0 / 65535.0, 80.0,      "%"),
    # HR 40-200 bpm
    "HR":   (160.0 / 65535.0, 40.0,         "bpm"),
    # ABP 0-200 mmHg
    "ABP":  (200.0 / 65535.0, 0.0,          "mmHg"),

    # ── 呼吸类 ──
    # RESP 双极性 ±50 %
    "RESP":     (100.0 / 65535.0, -50.0,     "%"),
    # RIP 双极性 ±1 V → 输出 mV
    "RIP":      (2000.0 / 65535.0, -1000.0, "mV"),
    # AIRFLOW ±10 L/min
    "AIRFLOW":  (20.0 / 65535.0, -10.0,     "L/min"),
    # CO2 0-60 mmHg
    "CO2":      (60.0 / 65535.0, 0.0,       "mmHg"),

    # ── 体温类 ──
    # TEMP 20-40 ℃
    "TEMP":         (20.0 / 65535.0, 20.0,  "C"),
    "BODYTEMP":     (20.0 / 65535.0, 20.0,  "C"),
    # AMBIENTTEMP -20~60 ℃
    "AMBIENTTEMP":  (80.0 / 65535.0, -20.0, "C"),

    # ── 运动与力学类 ──
    # XYZ ±2 g
    "XYZ":      (4.0 / 65535.0, -2.0,       "g"),
    # GYRO ±250 deg/s
    "GYRO":     (500.0 / 65535.0, -250.0,   "deg/s"),
    # MAG ±1000 uT
    "MAG":      (2000.0 / 65535.0, -1000.0, "uT"),
    # FORCE ±100 N
    "FORCE":    (200.0 / 65535.0, -100.0,   "N"),
    # PRESSURE 0-200 kPa
    "PRESSURE": (200.0 / 65535.0, 0.0,      "kPa"),
    # GONI ±180 deg
    "GONI":     (360.0 / 65535.0, -180.0,   "deg"),
    # TORQUE ±50 Nm
    "TORQUE":   (100.0 / 65535.0, -50.0,    "Nm"),

    # ── 光照与化学类 ──
    # LIGHT 0-1000 lux
    "LIGHT":    (1000.0 / 65535.0, 0.0,     "lux"),
    # UV 0-30 mW/cm2
    "UV":       (30.0 / 65535.0, 0.0,       "mW/cm2"),
    # PH 0-14
    "PH":       (14.0 / 65535.0, 0.0,       "pH"),
    # GLUCOSE 0-400 mg/dL
    "GLUCOSE":  (400.0 / 65535.0, 0.0,      "mg/dL"),

    # ── 触发与同步类（保持原值）──
    "TRIG":     (1.0, 0.0,                   "TTL"),
    "SYNC":     (1.0, 0.0,                   "event"),
    "EVENT":    (1.0, 0.0,                   "event"),
    "MARKER":   (1.0, 0.0,                   "event"),

    # ── 其他 ──
    # SOUND 0-120 dB
    "SOUND":    (120.0 / 65535.0, 0.0,      "dB"),
    # POSITION ±100 m
    "POSITION": (200.0 / 65535.0, -100.0,   "m"),
}


# ADC 分辨率（位）→ 满量程计数值
_MAX_COUNT = {
    8: 255.0,
    10: 1023.0,
    12: 4095.0,
    16: 65535.0,
    24: 16777215.0,
}


def calibrate_signal(raw_data: np.ndarray, sensor_type: str,
                      resolution: int = 16) -> np.ndarray:
    """将 ADC 原始值转换为物理量。

    Args:
        raw_data: ADC 原始整数值数组 (1D)
        sensor_type: 传感器类型标识（与 SENSOR_META 键一致）
        resolution: ADC 分辨率位数，默认 16

    Returns:
        物理量数组（单位见 CALIB_TABLE / SENSOR_META.unit）
    """
    try:
        data = np.asarray(raw_data, dtype=np.float64)

        # 触发/事件类直接返回原值
        if sensor_type in ("TRIG", "SYNC", "EVENT", "MARKER"):
            return data

        params = CALIB_TABLE.get(sensor_type)
        if params is None:
            # 未知传感器：通用 ADC→V 输出，假设双极性 ±1.5V
            logger.warning(f"未配置标定参数，使用默认双极性 ±1.5V 转换: {sensor_type}")
            max_count = _MAX_COUNT.get(resolution, 65535.0)
            v_adc = data * 3.3 / max_count
            unit = get_sensor_meta(sensor_type).unit
            if unit == "mV":
                gain = 1000.0
            elif unit == "uV":
                gain = 1000000.0
            else:
                gain = 1.0
            return (v_adc - 1.65) * gain

        scale, bias, _ = params

        # 若 resolution 与默认 16 位不一致，按比例缩放 scale
        if resolution != 16:
            default_max = 65535.0
            actual_max = _MAX_COUNT.get(resolution, 65535.0)
            scale = scale * (default_max / actual_max)

        physical = data * scale + bias
        return physical

    except Exception as e:
        logger.error(f"信号标定失败 [{sensor_type}]: {e}", exc_info=True)
        return np.asarray(raw_data, dtype=np.float64)


def get_sensor_unit(sensor_type: str) -> str:
    """获取传感器的物理量单位。"""
    return get_sensor_meta(sensor_type).unit


def is_calibrated(sensor_type: str) -> bool:
    """该传感器类型是否已配置标定参数。"""
    return sensor_type in CALIB_TABLE
