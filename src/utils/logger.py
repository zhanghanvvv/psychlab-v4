"""日志模块，统一管理 PsychLab V6 的日志输出。"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    """初始化全局日志器。

    Args:
        log_dir: 日志文件存放目录
        level: 日志级别

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger("PsychLab")
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # 文件输出
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_name = f"psychlab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_path / file_name, encoding="utf-8")
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


# 全局日志器实例
logger = setup_logger()
