"""LSL (Lab Streaming Layer) 数据源。

参考 SYNAPSE-DRIVE 的实现：通过 pylsl 接收 OpenSignals 等软件广播的生理数据流。
当用户没有 PLUX 原生库、或希望使用 OpenSignals 软件采集时，可选择 LSL 模式。

核心特性：
- 自动发现 LSL 流（关键词匹配：OpenSignals/ECG/EMG/EDA/EEG/Resp 等）
- 批量接收 pull_chunk 优化高频性能
- 指数退避重连机制
- 线程安全的数据回调
"""

import time
import threading
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass

from ..utils.logger import logger

# 尝试导入 pylsl
try:
    from pylsl import StreamInlet, resolve_streams, local_clock
    PYLSL_AVAILABLE = True
    # 全局解析锁，防止多线程并发 resolve_streams 死锁
    LSL_RESOLVE_LOCK = threading.Lock()
    logger.info("pylsl 模块已加载")
except ImportError:
    PYLSL_AVAILABLE = False
    logger.warning("pylsl 未安装，LSL 模式不可用。运行: pip install pylsl")


# 生理信号流关键词（用于自动匹配 LSL 流）
PHYSIOLOGY_KEYWORDS = [
    "OpenSignals", "BioSemi", "BioPac", "生理", "心电", "脑电", "肌电", "皮电",
    "EMG", "ECG", "EDA", "EEG", "GSR", "PPG", "BVP", "Resp", "RESP",
    "SpO2", "OXIMETER", "TEMP", "EOG", "EGG",
]


@dataclass
class LSLStreamInfo:
    """LSL 流信息。"""
    name: str
    stream_type: str
    channel_count: int
    nominal_srate: float
    source_id: str
    channel_names: List[str] = None
    raw_info: object = None  # pylsl.StreamInfo 原始对象（连接时直接使用，避免二次解析）

    def __repr__(self):
        return (f"LSLStream(name='{self.name}', type='{self.stream_type}', "
                f"channels={self.channel_count}, srate={self.nominal_srate}Hz)")


class LSLDataSource:
    """LSL 数据源，接收并分发生理数据流。

    用法:
        source = LSLDataSource()
        streams = source.discover_streams()
        source.connect(streams[0], on_data=callback)
        source.start()   # 启动接收线程
        ...
        source.stop()
        source.close()
    """

    def __init__(self, max_samples_per_pull: int = 1000,
                 pull_timeout: float = 0.005):
        """
        Args:
            max_samples_per_pull: 每次 pull_chunk 最大样本数
            pull_timeout: pull_chunk 超时(秒)，越小延迟越低
        """
        self._inlet: Optional[StreamInlet] = None
        self._stream_info: Optional[LSLStreamInfo] = None
        self._on_data_cb: Optional[Callable[[list, float], None]] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._max_samples = max_samples_per_pull
        self._pull_timeout = pull_timeout
        self._sample_count = 0
        self._last_timestamp = None
        self._reconnect = True
        self._max_retries = 5

    @property
    def is_available(self) -> bool:
        return PYLSL_AVAILABLE

    @property
    def is_connected(self) -> bool:
        return self._inlet is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stream_info(self) -> Optional[LSLStreamInfo]:
        return self._stream_info

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def last_timestamp(self) -> Optional[float]:
        return self._last_timestamp

    def discover_streams(self, wait_time: float = 12.0,
                          chunk: float = 2.0) -> List[LSLStreamInfo]:
        """发现可用的 LSL 流（内建重试，对抗多播丢包）。

        Windows + WiFi 环境下 LSL 多播发现存在间歇性丢包，
        单次 resolve_streams 经常超时。这里把总等待时间切成多个小段，
        反复解析，一旦发现流立即返回。

        Args:
            wait_time: 总等待预算(秒)，默认 12 秒
            chunk: 每次解析的等待时长(秒)

        Returns:
            LSLStreamInfo 列表（含原始 pylsl.StreamInfo，连接时无需二次解析）
        """
        if not PYLSL_AVAILABLE:
            return []

        streams = []
        deadline = time.time() + wait_time
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                with LSL_RESOLVE_LOCK:
                    streams = resolve_streams(wait_time=chunk)
            except Exception as e:
                logger.error(f"LSL 流发现失败: {e}")
                return []

            if streams:
                logger.info(f"第 {attempt} 次解析发现流")
                break
            logger.debug(f"LSL 第 {attempt} 次解析无结果，重试...")

        result = []
        for s in streams:
            # 提取通道名称（如果有；OpenSignals 通常不提供）
            channel_names = []
            try:
                desc = s.desc()
                chs = desc.child("channels").child("channel")
                for k in range(s.channel_count()):
                    name = chs.child_value("label")
                    channel_names.append(name if name else f"ch{k+1}")
                    chs = chs.next_sibling("channel")
            except Exception:
                channel_names = [f"ch{i+1}" for i in range(s.channel_count())]

            if not channel_names:
                channel_names = [f"ch{i+1}" for i in range(s.channel_count())]

            result.append(LSLStreamInfo(
                name=s.name(),
                stream_type=s.type(),
                channel_count=s.channel_count(),
                nominal_srate=s.nominal_srate(),
                source_id=s.source_id(),
                channel_names=channel_names,
                raw_info=s,  # 保存原始对象
            ))

        logger.info(f"发现 {len(result)} 个 LSL 流（共尝试 {attempt} 次）")
        return result

    def find_physiology_stream(self, wait_time: float = 3.0) -> Optional[LSLStreamInfo]:
        """自动查找生理信号流（关键词匹配）。

        参考 SYNAPSE-DRIVE 的匹配逻辑：名称或类型包含生理关键词。
        """
        streams = self.discover_streams(wait_time)
        for s in streams:
            name_lower = s.name.lower()
            type_lower = s.stream_type.lower()
            if any(kw.lower() in name_lower or kw.lower() in type_lower
                   for kw in PHYSIOLOGY_KEYWORDS):
                logger.info(f"找到生理信号流: {s.name} ({s.stream_type})")
                return s
        logger.warning("未找到匹配的生理信号流")
        return None

    def connect(self, stream: LSLStreamInfo,
                on_data: Callable[[list, float], None]) -> bool:
        """连接到指定 LSL 流。

        直接使用发现阶段保存的 pylsl.StreamInfo 原始对象创建 Inlet，
        不再二次 resolve_streams（二次解析在 Windows 上常因超时而失败）。

        Args:
            stream: LSLStreamInfo 对象（须来自 discover_streams）
            on_data: 数据回调 (sample_list, lsl_timestamp)

        Returns:
            连接成功返回 True
        """
        if not PYLSL_AVAILABLE:
            logger.error("pylsl 不可用，无法连接")
            return False

        try:
            target = stream.raw_info

            # 兜底：原始对象不存在时再解析（使用较长超时）
            if target is None:
                logger.warning("流对象缺失，重新解析（可能需要数秒）...")
                with LSL_RESOLVE_LOCK:
                    raw_streams = resolve_streams(wait_time=6.0)
                for rs in raw_streams:
                    if rs.name() == stream.name:
                        target = rs
                        break

            if target is None:
                logger.error(f"无法解析流: {stream.name}，"
                             f"请确认 OpenSignals 仍在运行且已开启 LSL")
                return False

            # max_buflen 加大缓冲，避免高频(1000Hz)数据丢帧
            self._inlet = StreamInlet(target, max_buflen=2000)
            self._stream_info = stream
            self._on_data_cb = on_data

            # 尝试打开流（部分 pylsl 版本自动完成）
            try:
                self._inlet.open_stream(timeout=5.0)
            except (AttributeError, TypeError):
                pass  # 旧版 pylsl 无 open_stream 或不接受参数，首次 pull 时自动打开

            logger.info(f"已连接 LSL 流: {stream.name}, "
                        f"{stream.channel_count}ch @ {stream.nominal_srate}Hz")
            return True

        except Exception as e:
            logger.error(f"LSL 连接失败: {e}", exc_info=True)
            self._inlet = None
            return False

    def start(self):
        """启动数据接收线程。"""
        if not self._inlet:
            logger.error("未连接 LSL 流，无法启动")
            return

        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        logger.info("LSL 数据接收线程已启动")

    def stop(self):
        """停止数据接收。"""
        self._running = False
        self._reconnect = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("LSL 数据接收已停止")

    def close(self):
        """关闭 LSL 连接。"""
        self.stop()
        if self._inlet:
            try:
                self._inlet.close_stream()
            except Exception:
                pass
            self._inlet = None
            logger.info("LSL 流已关闭")

    def _receive_loop(self):
        """数据接收主循环（运行在独立线程）。"""
        retry_count = 0
        while self._running:
            try:
                # 批量接收，提高高频性能
                samples, timestamps = self._inlet.pull_chunk(
                    timeout=self._pull_timeout,
                    max_samples=self._max_samples
                )

                if samples and timestamps:
                    self._sample_count += len(samples)
                    self._last_timestamp = timestamps[-1]

                    # 逐帧分发到回调（保持与 PLUX API onRawFrame 一致的接口）
                    for i in range(len(samples)):
                        if self._on_data_cb:
                            self._on_data_cb(samples[i], timestamps[i])

                    retry_count = 0
                else:
                    # 无数据时短暂休眠，避免空转
                    time.sleep(0.001)

            except Exception as e:
                retry_count += 1
                logger.warning(f"LSL 接收错误 (重试 {retry_count}): {e}")

                if not self._reconnect or retry_count >= self._max_retries:
                    logger.error("达到最大重试次数，停止接收")
                    break

                # 指数退避
                wait_time = min(retry_count * 0.5, 3.0)
                time.sleep(wait_time)

                # 尝试重连
                self._reconnect_stream()

    def _reconnect_stream(self):
        """重连 LSL 流。"""
        if not self._stream_info:
            return

        try:
            logger.info(f"尝试重连 LSL 流: {self._stream_info.name}")
            self.connect(self._stream_info, self._on_data_cb)
        except Exception as e:
            logger.error(f"重连失败: {e}")
