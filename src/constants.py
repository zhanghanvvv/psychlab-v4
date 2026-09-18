"""PsychLab V6 全局常量定义。

传感器类型枚举与 PLUX Python API 一致，
通道掩码、最大采样率等硬件约束来自 PLUX 官方文档。
"""

# ── 传感器类型枚举（与 PLUX API sensor.clas 一致）──
SENSOR_TYPES = {
    0:  "UNKNOWN",
    1:  "EMG",        # 肌电
    2:  "ECG",        # 心电
    3:  "LIGHT",      # 光照
    4:  "EDA",        # 皮电
    5:  "BVP",        # 容积脉搏
    6:  "RESP",       # 呼吸
    7:  "XYZ",        # 加速度
    8:  "SYNC",       # 同步
    9:  "EEG",        # 脑电
    10: "SYNC_ADAP",
    11: "SYNC_LED",
    12: "SYNC_SW",
    13: "USB",
    14: "FORCE",      # 力
    15: "TEMP",       # 体温
    16: "VPROBE",
    17: "BREAKOUT",
    18: "OXIMETER",   # 血氧
    19: "GONI",       # 关节角度
    20: "ACT",
    21: "EOG",        # 眼电
    22: "EGG",        # 胃电
    23: "ANSA",
    26: "OSL",
}

# 传感器中文名称
SENSOR_NAMES_CN = {
    # 生物电类
    "ECG":      "心电传感器",
    "EMG":      "肌电传感器",
    "EEG":      "脑电传感器",
    "EOG":      "眼电传感器",
    "EGG":      "胃电传感器",
    "ERG":      "视网膜电图传感器",
    # 阻抗/电导类
    "EDA":      "皮电传感器",
    "GSR":      "皮肤电阻传感器",
    # 心血管与血氧类
    "BVP":      "脉搏传感器",
    "PPG":      "光电容积传感器",
    "OXIMETER": "血氧传感器",
    "SpO2":     "血氧含量传感器",
    "HR":       "心率传感器",
    "ABP":      "动脉血压传感器",
    # 呼吸类
    "RESP":     "呼吸传感器",
    "RIP":      "呼吸感应体积描记传感器",
    "AIRFLOW":  "气流传感器",
    "CO2":      "二氧化碳传感器",
    # 体温类
    "TEMP":         "体温传感器",
    "BODYTEMP":     "体表温度传感器",
    "AMBIENTTEMP":  "环境温度传感器",
    # 运动与力学类
    "XYZ":      "加速度传感器",
    "GYRO":     "陀螺仪传感器",
    "MAG":      "磁力计传感器",
    "FORCE":    "力传感器",
    "PRESSURE": "压力传感器",
    "GONI":     "关节角度传感器",
    "TORQUE":   "扭矩传感器",
    # 光照与化学类
    "LIGHT":    "光照传感器",
    "UV":       "紫外线传感器",
    "PH":       "酸碱度传感器",
    "GLUCOSE":  "血糖传感器",
    # 触发与同步类
    "TRIG":     "信号触发传感器",
    "SYNC":     "同步传感器",
    "EVENT":    "事件标记传感器",
    "MARKER":   "标记传感器",
    # 其他
    "SOUND":    "声音传感器",
    "POSITION": "位置传感器",
    # 未知
    "UNKNOWN":  "未知传感器",
}

# ── 通道数 → 掩码映射 ──
# 掩码为 (1 << n) - 1，即前 n 位全1
CHANNEL_MASKS = {
    1: 0x01,   # 0b00000001
    2: 0x03,   # 0b00000011
    3: 0x07,   # 0b00000111
    4: 0x0F,   # 0b00001111
    5: 0x1F,   # 0b00011111
    6: 0x3F,   # 0b00111111
    7: 0x7F,   # 0b01111111
    8: 0xFF,   # 0b11111111
}

# ── 各通道数对应的最大采样率（Hz）──
# 来自 PLUX biosignalsplux Professional 规格表
MAX_SAMPLING_RATES = {
    1: 8000,
    2: 5000,
    3: 4000,   # 满足 docx ≥4000Hz 要求
    4: 3000,
    5: 3000,
    6: 2000,
    7: 2000,
    8: 2000,
}

# ── 分辨率 ──
DEFAULT_RESOLUTION = 16  # 16-bit per channel

# ── 传感器颜色映射（PLUX API sensor.color）──
SENSOR_COLORS = {
    0: "UNKNOWN",
    1: "BLACK",
    2: "GRAY",
    3: "WHITE",
    4: "DARKBLUE",
    5: "LIGHTBLUE",
    6: "RED",
    7: "GREEN",
    8: "YELLOW",
    9: "ORANGE",
}

# ── 事件标记类型 ──
EVENT_TYPES = {
    "TASK_START":    "任务开始",
    "TASK_END":      "任务结束",
    "PHASE_CHANGE":  "阶段切换",
    "MANUAL":        "手动标记",
    "DIGITAL_TRIG":  "数字触发",
    "RECORD_START":  "采集开始",
    "RECORD_END":    "采集结束",
}

# ── 默认通道显示颜色 ──
CHANNEL_COLORS = [
    "#e74c3c",  # 红
    "#2ecc71",  # 绿
    "#3498db",  # 蓝
    "#f39c12",  # 橙
    "#9b59b6",  # 紫
    "#1abc9c",  # 青
    "#e67e22",  # 深橙
    "#95a5a6",  # 灰
]
