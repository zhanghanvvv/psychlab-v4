"""采集阶段记录器。

静息态、任务态、恢复态为三次相互独立的采集会话，
每次采集开始前在界面下拉框中选定本次采集所属阶段，
该阶段标签随数据一起写入文件，供离线分析时区分数据段。
"""

import time
from datetime import datetime
from dataclasses import dataclass

from PySide6.QtCore import QObject

# 三个采集阶段
PHASE_REST = "静息态"
PHASE_TASK = "任务态"
PHASE_RECOVERY = "恢复态"
PHASES = (PHASE_REST, PHASE_TASK, PHASE_RECOVERY)


@dataclass
class PhaseEvent:
    """采集记录（用于写入 HDF5 事件表）。"""
    timestamp: float      # 相对采集开始的秒数
    abs_time: str         # 绝对时间 ISO 格式
    event: str            # RECORD_START / RECORD_END
    phase: str            # 本次采集阶段
    n_seq: int = 0


class TaskController(QObject):
    """单次采集的阶段记录器（不做阶段切换）。"""

    def __init__(self):
        super().__init__()
        self._phase: str = ""
        self._events: list[PhaseEvent] = []
        self._start_time = 0.0

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def events(self) -> list[PhaseEvent]:
        return self._events

    def set_acquisition_start(self, phase: str = PHASE_REST, n_seq: int = 0):
        """采集开始：记录时间基准与本次采集阶段。"""
        self._phase = phase if phase in PHASES else PHASE_REST
        self._start_time = time.time()
        self._events = [
            PhaseEvent(
                timestamp=0.0,
                abs_time=datetime.now().isoformat(),
                event="RECORD_START",
                phase=self._phase,
                n_seq=n_seq,
            )
        ]
        from ..utils.logger import logger
        logger.info(f"采集开始，阶段: {self._phase}")

    def get_elapsed_time(self) -> float:
        """相对采集开始的秒数。"""
        if self._start_time == 0:
            return 0.0
        return time.time() - self._start_time

    def stop_all(self):
        """采集结束：追加结束记录。"""
        self._events.append(PhaseEvent(
            timestamp=self.get_elapsed_time(),
            abs_time=datetime.now().isoformat(),
            event="RECORD_END",
            phase=self._phase,
        ))
        phase = self._phase
        self._phase = ""
        from ..utils.logger import logger
        logger.info(f"采集结束，阶段: {phase}")

    def get_events_as_dict(self) -> list[dict]:
        """转为字典列表（写入 HDF5）。"""
        return [
            {
                "timestamp": e.timestamp,
                "abs_time": e.abs_time,
                "event_type": e.event,
                "task_id": e.phase,
                "description": f"{e.event}: {e.phase}",
                "n_seq": e.n_seq,
            }
            for e in self._events
        ]
