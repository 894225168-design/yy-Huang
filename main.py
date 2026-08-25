"""鼠标键盘操作录制工具 — 入口。"""

import sys

from PyQt5.QtWidgets import QApplication

from main_window import MainWindow, APP_TITLE, APP_STYLE
from recorder import ensure_dpi_awareness


def main():
    # 高分屏下保证录制/回放坐标系一致（物理像素），必须在创建窗口前调用
    ensure_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyleSheet(APP_STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
