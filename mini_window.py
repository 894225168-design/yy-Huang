"""悬浮小窗：录制/回放运行时自动缩小的迷你控制条。

设计要点：
- 无边框、置顶、可拖拽（按住空白处拖动），默认停靠屏幕底部中央。
- 显示：状态圆点+文字+已用时长、暂停/停止按钮、事件数、回放速度、展开/关闭按钮。
- 仅通过信号与主窗口交互（pause/stop/expand），不直接操作录制与回放逻辑。
- 圆角外观通过外层透明背景 + 内层圆角面板实现，附投影。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame, QApplication,
    QGraphicsDropShadowEffect,
)

MINI_STYLE = """
QWidget { font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif; }

QFrame#miniPanel {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 22px;
}

QLabel { color: #1F2329; font-size: 12px; background: transparent; }
QLabel#stateLabel { font-weight: bold; }
QLabel#timeLabel { color: #4B5563; }
QLabel#infoLabel { color: #6B7280; }

QPushButton#miniBtn {
    background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 13px;
    padding: 4px 12px; font-size: 12px; color: #1F2329;
}
QPushButton#miniBtn:hover { background: #F3F4F6; }
QPushButton#miniBtn[active="true"] {
    background: #FDE68A; border-color: #F59E0B; color: #92400E;
}

QPushButton#iconBtn {
    background: transparent; border: none; border-radius: 10px;
    font-size: 13px; color: #6B7280; padding: 2px 6px;
}
QPushButton#iconBtn:hover { background: #F1F2F4; color: #1F2329; }

QPushButton#closeBtn {
    background: transparent; border: none; border-radius: 10px;
    font-size: 13px; color: #9CA3AF; padding: 2px 6px;
}
QPushButton#closeBtn:hover { background: #FEF2F2; color: #DC2626; }
"""


class MiniWindow(QWidget):
    """悬浮迷你控制条。"""

    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    expand_clicked = pyqtSignal()   # ▼ 展开完整界面 / ✕ 关闭小窗 都会触发

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        # 外层透明，内层面板圆角（否则圆角外是矩形白边）
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(MINI_STYLE)

        panel = QFrame(self)
        panel.setObjectName("miniPanel")
        lay = QHBoxLayout(panel)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(10)

        # 状态圆点 + 状态文字 + 时长
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        lay.addWidget(self.dot)
        self.state_label = QLabel("就绪")
        self.state_label.setObjectName("stateLabel")
        lay.addWidget(self.state_label)
        self.time_label = QLabel("")
        self.time_label.setObjectName("timeLabel")
        lay.addWidget(self.time_label)

        # 暂停 / 停止
        self.btn_pause = QPushButton("⏸  暂停  F8")
        self.btn_pause.setObjectName("miniBtn")
        self.btn_pause.setToolTip("暂停/继续（F8）")
        self.btn_pause.clicked.connect(self.pause_clicked)
        lay.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("■  停止")
        self.btn_stop.setObjectName("miniBtn")
        self.btn_stop.setToolTip("停止当前的录制或回放")
        self.btn_stop.clicked.connect(self.stop_clicked)
        lay.addWidget(self.btn_stop)

        # 事件数 / 回放速度
        self.count_label = QLabel("")
        self.count_label.setObjectName("infoLabel")
        lay.addWidget(self.count_label)
        self.speed_label = QLabel("")
        self.speed_label.setObjectName("infoLabel")
        lay.addWidget(self.speed_label)

        # 展开完整界面 / 关闭小窗
        self.btn_expand = QPushButton("▼")
        self.btn_expand.setObjectName("iconBtn")
        self.btn_expand.setFixedWidth(28)
        self.btn_expand.setToolTip("展开完整界面（不影响当前录制/回放）")
        self.btn_expand.clicked.connect(self.expand_clicked)
        lay.addWidget(self.btn_expand)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setFixedWidth(28)
        self.btn_close.setToolTip("关闭小窗，回到完整界面")
        self.btn_close.clicked.connect(self.expand_clicked)
        lay.addWidget(self.btn_close)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        # 投影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 45))
        panel.setGraphicsEffect(shadow)

        self._drag_pos = None

    # ---------- 展示接口 ----------

    def set_state(self, text: str, color: str):
        """设置状态文字与圆点颜色。"""
        self.dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        self.state_label.setText(text)

    def set_time(self, text: str):
        self.time_label.setText(text)

    def set_count(self, text: str):
        self.count_label.setText(text)

    def set_speed(self, text: str):
        self.speed_label.setText(text)

    def set_pause_active(self, paused: bool):
        """切换暂停按钮的显示（暂停中显示为继续）。"""
        if paused:
            self.btn_pause.setText("▶  继续  F8")
        else:
            self.btn_pause.setText("⏸  暂停  F8")
        self.btn_pause.setProperty("active", paused)
        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)

    # ---------- 位置 ----------

    def show_at_default_position(self):
        """停靠屏幕底部中央显示。"""
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + screen.height() - self.height() - 60
        self.move(x, y)
        self.show()
        self.raise_()

    # ---------- 拖拽 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
