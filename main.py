"""PsychLab V4 主入口。

生理信号采集分析系统，用于 biosignalsplux 设备数据采集与分析。
模拟飞行系统全程生理数据采集与事件标记。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from src.ui.main_window import MainWindow
from src.utils.logger import logger


def main():
    """启动 PsychLab V4。"""
    logger.info("=" * 50)
    logger.info("PsychLab V4 启动中...")
    logger.info("=" * 50)

    # 高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PsychLab V4")
    app.setOrganizationName("PsychLab")

    # 设置应用样式
    app.setStyle("Fusion")

    # 创建主窗口
    window = MainWindow()
    window.show()

    logger.info("PsychLab V4 已启动")

    # 运行事件循环
    ret = app.exec()

    logger.info("PsychLab V4 已退出")
    sys.exit(ret)


if __name__ == "__main__":
    main()
