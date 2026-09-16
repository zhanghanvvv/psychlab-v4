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

    # 蓝白色全局样式表 + 增大字体
    app.setStyleSheet("""
        /* 全局基础 */
        QWidget {
            background-color: #f4f8ff;
            color: #1a3a6b;
            font-size: 14px;
        }
        /* 主窗口 */
        QMainWindow {
            background-color: #ffffff;
        }
        /* 菜单栏 */
        QMenuBar {
            background-color: #ffffff;
            color: #1a3a6b;
            font-size: 14px;
            font-weight: bold;
            border-bottom: 1px solid #c5d4ec;
            padding: 4px;
        }
        QMenuBar::item {
            background: transparent;
            padding: 6px 14px;
            border-radius: 4px;
        }
        QMenuBar::item:selected {
            background-color: #e3edfa;
        }
        QMenu {
            background-color: #ffffff;
            color: #1a3a6b;
            border: 1px solid #c5d4ec;
            padding: 6px;
        }
        QMenu::item {
            padding: 6px 24px;
            border-radius: 4px;
        }
        QMenu::item:selected {
            background-color: #e3edfa;
        }
        /* 状态栏 */
        QStatusBar {
            background-color: #ffffff;
            color: #1a3a6b;
            font-size: 13px;
            border-top: 1px solid #c5d4ec;
        }
        QStatusBar::item { border: none; }
        /* 分组框 */
        QGroupBox {
            background-color: #ffffff;
            color: #1976d2;
            font-size: 14px;
            font-weight: bold;
            border: 1px solid #c5d4ec;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: #1976d2;
        }
        /* 标签 */
        QLabel {
            color: #1a3a6b;
            font-size: 14px;
            background: transparent;
        }
        /* 滚动区域 */
        QScrollArea {
            background-color: #f4f8ff;
            border: none;
        }
        /* 表格 */
        QTableWidget {
            background-color: #ffffff;
            alternate-background-color: #f4f8ff;
            color: #1a3a6b;
            font-size: 13px;
            gridline-color: #c5d4ec;
            border: 1px solid #c5d4ec;
            border-radius: 4px;
        }
        QHeaderView::section {
            background-color: #1976d2;
            color: white;
            font-weight: bold;
            padding: 6px;
            border: none;
            border-right: 1px solid #2196f3;
        }
        QTableWidget::item:selected {
            background-color: #e3edfa;
            color: #1a3a6b;
        }
        /* 下拉框 */
        QComboBox {
            background-color: #ffffff;
            color: #1a3a6b;
            font-size: 14px;
            border: 1px solid #c5d4ec;
            border-radius: 4px;
            padding: 5px 8px;
            min-height: 22px;
        }
        QComboBox:hover {
            border-color: #1976d2;
        }
        QComboBox::drop-down {
            border: none;
            width: 22px;
        }
        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #1a3a6b;
            selection-background-color: #e3edfa;
            selection-color: #1a3a6b;
            border: 1px solid #c5d4ec;
            outline: none;
        }
        /* 数字输入框 */
        QSpinBox {
            background-color: #ffffff;
            color: #1a3a6b;
            font-size: 14px;
            border: 1px solid #c5d4ec;
            border-radius: 4px;
            padding: 5px 8px;
            min-height: 22px;
        }
        QSpinBox:hover { border-color: #1976d2; }
        /* 复选框 */
        QCheckBox {
            color: #1a3a6b;
            font-size: 14px;
            spacing: 6px;
        }
        /* 选项卡 */
        QTabWidget::pane {
            background-color: #ffffff;
            border: 1px solid #c5d4ec;
            border-top: none;
            border-radius: 0 0 4px 4px;
        }
        QTabBar::tab {
            background-color: #e3edfa;
            color: #1a3a6b;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 18px;
            border: 1px solid #c5d4ec;
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #1976d2;
            color: white;
        }
        QTabBar::tab:hover:!selected {
            background-color: #c5d4ec;
        }
        /* 滚动条 */
        QScrollBar:vertical {
            background: #f4f8ff;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #c5d4ec;
            border-radius: 4px;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover { background: #1976d2; }
        QScrollBar:horizontal {
            background: #f4f8ff;
            height: 12px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #c5d4ec;
            border-radius: 4px;
            min-width: 30px;
        }
        QScrollBar::handle:horizontal:hover { background: #1976d2; }
        QScrollBar::add-line, QScrollBar::sub-line { border: none; height: 0; width: 0; }
        /* 普通按钮（蓝白主色） */
        QPushButton {
            background-color: #1976d2;
            color: white;
            font-size: 14px;
            font-weight: bold;
            border: none;
            border-radius: 4px;
            padding: 6px 14px;
            min-height: 24px;
        }
        QPushButton:hover { background-color: #2196f3; }
        QPushButton:pressed { background-color: #0d47a1; }
        QPushButton:disabled {
            background-color: #c5d4ec;
            color: #7f8c8d;
        }
    """)

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
