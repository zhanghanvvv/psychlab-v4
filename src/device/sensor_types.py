"""传感器元数据定义。

每种传感器包含：显示名称、单位、量程、默认滤波参数、显示颜色。
用于 UI 显示和数据物理量转换。
共 30+ 种传感器类型，覆盖 biosignalsplux 全系列及常见生理信号。
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class SensorMeta:
    """传感器元数据。"""
    name: str               # 英文标识（如 "ECG"）
    name_cn: str            # 中文名称
    unit: str               # 物理单位（如 "mV"）
    y_range: Tuple[float, float]  # 默认Y轴显示范围
    filter_low: Optional[float]   # 带通下限 (Hz)，None=不滤波
    filter_high: Optional[float]  # 带通上限 (Hz)
    notch_freq: Optional[float]   # 陷波频率 (Hz)，通常为50Hz工频
    color: str = ""         # 显示颜色

    @property
    def needs_filter(self) -> bool:
        """是否需要滤波。"""
        return self.filter_low is not None or self.filter_high is not None


# ── 预定义传感器元数据（30+ 种）──
SENSOR_META: dict[str, SensorMeta] = {
    # === 生物电类 ===
    "ECG": SensorMeta(
        name="ECG", name_cn="心电传感器", unit="mV",
        y_range=(-2.0, 2.0), filter_low=0.5, filter_high=40.0, notch_freq=50.0,
    ),
    "EMG": SensorMeta(
        name="EMG", name_cn="肌电传感器", unit="mV",
        y_range=(-1.0, 1.0), filter_low=20.0, filter_high=500.0, notch_freq=50.0,
    ),
    "EEG": SensorMeta(
        name="EEG", name_cn="脑电传感器", unit="uV",
        y_range=(-100.0, 100.0), filter_low=0.5, filter_high=50.0, notch_freq=50.0,
    ),
    "EOG": SensorMeta(
        name="EOG", name_cn="眼电传感器", unit="mV",
        y_range=(-1.0, 1.0), filter_low=0.5, filter_high=30.0, notch_freq=50.0,
    ),
    "EGG": SensorMeta(
        name="EGG", name_cn="胃电传感器", unit="mV",
        y_range=(-1.0, 1.0), filter_low=0.5, filter_high=30.0, notch_freq=50.0,
    ),
    "ERG": SensorMeta(
        name="ERG", name_cn="视网膜电图传感器", unit="uV",
        y_range=(-50.0, 50.0), filter_low=0.5, filter_high=300.0, notch_freq=50.0,
    ),

    # === 阻抗/电导类 ===
    "EDA": SensorMeta(
        name="EDA", name_cn="皮电传感器", unit="uS",
        y_range=(0.0, 20.0), filter_low=0.5, filter_high=5.0, notch_freq=None,
    ),
    "GSR": SensorMeta(
        name="GSR", name_cn="皮肤电阻传感器", unit="kOhm",
        y_range=(0.0, 500.0), filter_low=None, filter_high=5.0, notch_freq=None,
    ),

    # === 心血管与血氧类 ===
    "BVP": SensorMeta(
        name="BVP", name_cn="脉搏传感器", unit="mV",
        y_range=(-1.0, 1.0), filter_low=0.5, filter_high=10.0, notch_freq=None,
    ),
    "PPG": SensorMeta(
        name="PPG", name_cn="光电容积传感器", unit="mV",
        y_range=(-1.0, 1.0), filter_low=0.5, filter_high=10.0, notch_freq=None,
    ),
    "OXIMETER": SensorMeta(
        name="OXIMETER", name_cn="血氧传感器", unit="%",
        y_range=(80.0, 100.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "SpO2": SensorMeta(
        name="SpO2", name_cn="血氧含量传感器", unit="%",
        y_range=(80.0, 100.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "HR": SensorMeta(
        name="HR", name_cn="心率传感器", unit="bpm",
        y_range=(40.0, 200.0), filter_low=0.5, filter_high=5.0, notch_freq=None,
    ),
    "ABP": SensorMeta(
        name="ABP", name_cn="动脉血压传感器", unit="mmHg",
        y_range=(0.0, 200.0), filter_low=0.1, filter_high=20.0, notch_freq=None,
    ),

    # === 呼吸类 ===
    "RESP": SensorMeta(
        name="RESP", name_cn="呼吸传感器", unit="%",
        y_range=(-50.0, 50.0), filter_low=0.1, filter_high=2.0, notch_freq=None,
    ),
    "RIP": SensorMeta(
        name="RIP", name_cn="呼吸感应体积描记传感器", unit="V",
        y_range=(-1.0, 1.0), filter_low=0.1, filter_high=2.0, notch_freq=None,
    ),
    "AIRFLOW": SensorMeta(
        name="AIRFLOW", name_cn="气流传感器", unit="L/min",
        y_range=(-10.0, 10.0), filter_low=0.1, filter_high=5.0, notch_freq=None,
    ),
    "CO2": SensorMeta(
        name="CO2", name_cn="二氧化碳传感器", unit="mmHg",
        y_range=(0.0, 60.0), filter_low=None, filter_high=5.0, notch_freq=None,
    ),

    # === 体温类 ===
    "TEMP": SensorMeta(
        name="TEMP", name_cn="体温传感器", unit="C",
        y_range=(20.0, 40.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "BODYTEMP": SensorMeta(
        name="BODYTEMP", name_cn="体表温度传感器", unit="C",
        y_range=(20.0, 40.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "AMBIENTTEMP": SensorMeta(
        name="AMBIENTTEMP", name_cn="环境温度传感器", unit="C",
        y_range=(-20.0, 60.0), filter_low=None, filter_high=None, notch_freq=None,
    ),

    # === 运动与力学类 ===
    "XYZ": SensorMeta(
        name="XYZ", name_cn="加速度传感器", unit="g",
        y_range=(-2.0, 2.0), filter_low=0.1, filter_high=10.0, notch_freq=None,
    ),
    "GYRO": SensorMeta(
        name="GYRO", name_cn="陀螺仪传感器", unit="deg/s",
        y_range=(-250.0, 250.0), filter_low=0.1, filter_high=50.0, notch_freq=None,
    ),
    "MAG": SensorMeta(
        name="MAG", name_cn="磁力计传感器", unit="uT",
        y_range=(-1000.0, 1000.0), filter_low=None, filter_high=10.0, notch_freq=None,
    ),
    "FORCE": SensorMeta(
        name="FORCE", name_cn="力传感器", unit="N",
        y_range=(-100.0, 100.0), filter_low=0.1, filter_high=100.0, notch_freq=None,
    ),
    "PRESSURE": SensorMeta(
        name="PRESSURE", name_cn="压力传感器", unit="kPa",
        y_range=(0.0, 200.0), filter_low=None, filter_high=50.0, notch_freq=None,
    ),
    "GONI": SensorMeta(
        name="GONI", name_cn="关节角度传感器", unit="deg",
        y_range=(-180.0, 180.0), filter_low=0.1, filter_high=10.0, notch_freq=None,
    ),
    "TORQUE": SensorMeta(
        name="TORQUE", name_cn="扭矩传感器", unit="Nm",
        y_range=(-50.0, 50.0), filter_low=0.1, filter_high=50.0, notch_freq=None,
    ),

    # === 光照与化学类 ===
    "LIGHT": SensorMeta(
        name="LIGHT", name_cn="光照传感器", unit="lux",
        y_range=(0.0, 1000.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "UV": SensorMeta(
        name="UV", name_cn="紫外线传感器", unit="mW/cm2",
        y_range=(0.0, 30.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "PH": SensorMeta(
        name="PH", name_cn="酸碱度传感器", unit="pH",
        y_range=(0.0, 14.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "GLUCOSE": SensorMeta(
        name="GLUCOSE", name_cn="血糖传感器", unit="mg/dL",
        y_range=(0.0, 400.0), filter_low=None, filter_high=None, notch_freq=None,
    ),

    # === 触发与同步类 ===
    "TRIG": SensorMeta(
        name="TRIG", name_cn="信号触发传感器", unit="TTL",
        y_range=(0.0, 5.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "SYNC": SensorMeta(
        name="SYNC", name_cn="同步传感器", unit="event",
        y_range=(0.0, 1.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "EVENT": SensorMeta(
        name="EVENT", name_cn="事件标记传感器", unit="event",
        y_range=(0.0, 1.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
    "MARKER": SensorMeta(
        name="MARKER", name_cn="标记传感器", unit="event",
        y_range=(0.0, 1.0), filter_low=None, filter_high=None, notch_freq=None,
    ),

    # === 其他 ===
    "SOUND": SensorMeta(
        name="SOUND", name_cn="声音传感器", unit="dB",
        y_range=(0.0, 120.0), filter_low=20.0, filter_high=20000.0, notch_freq=None,
    ),
    "POSITION": SensorMeta(
        name="POSITION", name_cn="位置传感器", unit="m",
        y_range=(-100.0, 100.0), filter_low=None, filter_high=10.0, notch_freq=None,
    ),

    "UNKNOWN": SensorMeta(
        name="UNKNOWN", name_cn="未知传感器", unit="raw",
        y_range=(-100.0, 100.0), filter_low=None, filter_high=None, notch_freq=None,
    ),
}


def get_sensor_meta(sensor_name: str) -> SensorMeta:
    """根据传感器类型名称获取元数据，未知类型返回 UNKNOWN。"""
    return SENSOR_META.get(sensor_name, SENSOR_META["UNKNOWN"])
