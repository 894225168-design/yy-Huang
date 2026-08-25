"""GUI 主窗口：连接录制器、回放器与脚本存储。

UI 风格：现代扁平化 —— 浅色背景、白色圆角面板、细边框、
结构化事件表格（类型着色）、状态圆点指示、淡彩强调按钮。
"""

import os
import sys
from datetime import datetime

from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QComboBox, QSpinBox,
    QCheckBox, QLabel, QFileDialog, QMessageBox, QFrame,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget,
    QAbstractItemView, QInputDialog,
)

from event_types import (
    RecordedEvent, EV_MOUSE_CLICK, EV_MOUSE_MOVE, EV_MOUSE_SCROLL,
    EV_KEY_PRESS, EV_KEY_RELEASE,
)
from mini_window import MiniWindow
from player import Player
from recorder import Recorder
from storage import Script, ScriptStorage

APP_TITLE = "鼠标键盘操作录制工具"

# 数据存储目录：
# - 源码运行：脚本所在目录（main_window.py 旁的 scripts/）
# - PyInstaller 打包运行：__file__ 指向临时解压目录（_MEIxxxxx），
#   exe 关闭后会被自动清理导致录制全部丢失——必须改用 exe 所在目录，
#   这样 scripts/ 持久保存在 exe 旁边，跨多次启动不丢数据。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 表格渲染上限：大量事件（如开启鼠标移动轨迹）时防止界面卡顿
MAX_DISPLAY_ROWS = 5000

# 事件类型在表格中的颜色
TYPE_COLORS = {
    EV_MOUSE_CLICK: "#2563EB",
    EV_MOUSE_MOVE: "#9CA3AF",
    EV_MOUSE_SCROLL: "#D97706",
    EV_KEY_PRESS: "#7C3AED",
    EV_KEY_RELEASE: "#7C3AED",
}

# 状态圆点颜色
STATE_COLORS = {
    "idle": "#22C55E",
    "recording": "#EF4444",
    "playing": "#3B82F6",
    "paused": "#F59E0B",
}

APP_STYLE = """
QWidget {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1F2329;
}
QMainWindow, QWidget#centralRoot { background: #F4F5F7; }

QFrame#panel { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 10px; }

QLabel#sectionTitle { font-weight: bold; font-size: 13px; color: #1F2329; }
QLabel#subLabel { color: #9CA3AF; font-size: 12px; }
QLabel#hintLabel { color: #9CA3AF; font-size: 13px; }

QPushButton {
    background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 8px;
    padding: 7px 14px;
}
QPushButton:hover { background: #F3F4F6; }
QPushButton:pressed { background: #E5E7EB; }
QPushButton:disabled { color: #9CA3AF; background: #F9FAFB; border-color: #E5E7EB; }

QPushButton#iconBtn {
    background: transparent; border: none; border-radius: 6px;
    font-size: 15px; color: #6B7280; padding: 0px;
}
QPushButton#iconBtn:hover { background: #F1F2F4; color: #1F2329; }

QPushButton#btnRecord {
    background: #FEF2F2; border: 1px solid #FECACA; color: #DC2626; font-weight: bold;
}
QPushButton#btnRecord:hover { background: #FEE2E2; }
QPushButton#btnRecord[active="true"] {
    background: #DC2626; border-color: #DC2626; color: #FFFFFF;
}

QPushButton#btnPlay {
    background: #EFF6FF; border: 1px solid #BFDBFE; color: #2563EB; font-weight: bold;
}
QPushButton#btnPlay:hover { background: #DBEAFE; }
QPushButton#btnPlay[active="true"] {
    background: #2563EB; border-color: #2563EB; color: #FFFFFF;
}

QPushButton#btnPause {
    background: #FFFBEB; border: 1px solid #FDE68A; color: #D97706; font-weight: bold;
}
QPushButton#btnPause:hover { background: #FEF3C7; }
QPushButton#btnPause[active="true"] {
    background: #D97706; border-color: #D97706; color: #FFFFFF;
}
QPushButton#btnPause:disabled {
    color: #9CA3AF; background: #F9FAFB; border-color: #E5E7EB;
}

QPushButton#btnInsert {
    background: #F5F3FF; border: 1px solid #DDD6FE; color: #7C3AED; font-weight: bold;
}
QPushButton#btnInsert:hover { background: #EDE9FE; }
QPushButton#btnInsert[active="true"] {
    background: #7C3AED; border-color: #7C3AED; color: #FFFFFF;
}
QPushButton#btnInsert:disabled {
    color: #9CA3AF; background: #F9FAFB; border-color: #E5E7EB;
}

QPushButton#btnStop {
    background: #FFFFFF; border: 1px solid #D9DCE1; color: #4B5563; font-weight: bold;
}
QPushButton#btnStop:hover { background: #F3F4F6; }

QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 6px; padding: 8px 10px; color: #1F2329; }
QListWidget::item:hover:!selected { background: #F3F4F6; }
QListWidget::item:selected { background: #EFF6FF; color: #1D4ED8; }

QStackedWidget { background: transparent; }

QTableWidget {
    background: #FFFFFF; border: 1px solid #ECECEF; border-radius: 8px;
    gridline-color: transparent; selection-background-color: #EFF6FF;
    selection-color: #1F2329; alternate-background-color: #F8F9FB;
    font-size: 12px;
}
QTableWidget::item { padding: 4px 8px; border: none; }
QHeaderView::section {
    background: #F8F9FB; color: #6B7280; border: none;
    border-bottom: 1px solid #ECECEF; padding: 6px 8px;
}

QComboBox, QSpinBox {
    background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 6px; padding: 5px 8px;
}
QComboBox:hover, QSpinBox:hover { border-color: #9CA3AF; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView {
    background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 6px;
    selection-background-color: #EFF6FF; selection-color: #1D4ED8; outline: none;
}

QCheckBox { color: #4B5563; spacing: 6px; }

QStatusBar { background: #FFFFFF; border-top: 1px solid #ECECEF; }
QStatusBar::item { border: none; }

QSplitter::handle { background: transparent; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D1D5DB; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #9CA3AF; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #D1D5DB; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QToolTip {
    background: #1F2329; color: #FFFFFF; border: none;
    padding: 6px 8px; border-radius: 6px;
}
"""


class Signals(QObject):
    """跨线程信号：pynput 监听线程 / 回放线程 -> UI 主线程。"""
    event_recorded = pyqtSignal(object)      # RecordedEvent
    hotkey_pressed = pyqtSignal(str)         # 热键名
    play_progress = pyqtSignal(int, int)     # 已完成, 总数
    play_finished = pyqtSignal(bool)         # 是否被手动停止


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = Signals()
        self.storage = ScriptStorage(BASE_DIR)

        # 录制中的事件缓冲（批量刷新 UI，避免鼠标移动刷屏）
        self._pending_events: list[RecordedEvent] = []
        self._recorded_count = 0

        # 插入录制模式：回放暂停期间录制一段新操作，插入到暂停位置
        self._insert_mode = False
        self._insert_count = 0

        # 悬浮小窗：录制/回放运行时自动缩小主窗口
        self.mini = MiniWindow()
        self.mini.pause_clicked.connect(self._toggle_pause)
        self.mini.stop_clicked.connect(self._on_mini_stop)
        self.mini.expand_clicked.connect(self._expand_from_mini)
        self._mini_mode: str | None = None       # recording / playing / insert
        self._last_progress: tuple[int, int] = (0, 0)

        self.recorder = Recorder(
            on_event=self._on_event_threadsafe,
            on_hotkey=self._on_hotkey_threadsafe,
            record_mouse_move=True,
        )
        self.player = Player(
            on_progress=self._on_progress_threadsafe,
            on_finished=self._on_finished_threadsafe,
        )

        self.scripts: list[Script] = []
        self.current_script: Script | None = None

        self._init_ui()
        self._connect_signals()
        self._load_scripts()

        # 启动常驻键盘监听（热键 + 录制）
        self.recorder.start_listening()

        # 录制期间批量刷新时间线的定时器
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(200)
        self._flush_timer.timeout.connect(self._flush_pending_events)

        # 悬浮小窗内容刷新定时器（状态/时长/事件数）
        self._mini_timer = QTimer(self)
        self._mini_timer.setInterval(200)
        self._mini_timer.timeout.connect(self._update_mini)

    # ---------- UI 构建 ----------

    def _init_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(1080, 680)

        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # 中部：左脚本列表 + 右事件时间线（可拖拽分隔）
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 740])
        root.addWidget(splitter, 1)

        # 底部控制区
        root.addWidget(self._build_bottom_panel())

        # 状态栏：左侧 状态圆点+文字，右侧 当前脚本信息
        self._init_status_bar()

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(240)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(4)
        title = QLabel("脚本列表")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        b_add = QPushButton("+")
        b_add.setObjectName("iconBtn")
        b_add.setFixedSize(26, 26)
        b_add.setToolTip("新建脚本")
        b_add.clicked.connect(self._on_new_script)
        header.addWidget(b_add)
        lay.addLayout(header)

        self.script_list = QListWidget()
        self.script_list.itemSelectionChanged.connect(self._on_script_selected)
        lay.addWidget(self.script_list, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        b_rename = QPushButton("重命名")
        b_rename.clicked.connect(self._on_rename_script)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._on_delete_script)
        row.addWidget(b_rename, 1)
        row.addWidget(b_del, 1)
        lay.addLayout(row)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("事件时间线")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.count_label = QLabel("0 条事件")
        self.count_label.setObjectName("subLabel")
        header.addWidget(self.count_label)
        lay.addLayout(header)

        self.timeline_stack = QStackedWidget()
        self.hint_page = QLabel("选择脚本查看录制的事件\n或按 F9 开始录制")
        self.hint_page.setObjectName("hintLabel")
        self.hint_page.setAlignment(Qt.AlignCenter)
        self.event_table = self._build_event_table()
        self.timeline_stack.addWidget(self.hint_page)
        self.timeline_stack.addWidget(self.event_table)
        lay.addWidget(self.timeline_stack, 1)
        return panel

    def _build_event_table(self) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["#", "时间", "类型", "详情"])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 80)
        table.setColumnWidth(2, 84)
        vh = table.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(26)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setFocusPolicy(Qt.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return table

    def _build_bottom_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.btn_record = QPushButton("●  开始录制  F9")
        self.btn_record.setObjectName("btnRecord")
        self.btn_record.setMinimumHeight(40)
        self.btn_record.clicked.connect(self._toggle_record)
        row1.addWidget(self.btn_record, 1)

        self.btn_play = QPushButton("▶  开始回放  F10")
        self.btn_play.setObjectName("btnPlay")
        self.btn_play.setMinimumHeight(40)
        self.btn_play.clicked.connect(self._toggle_play)
        row1.addWidget(self.btn_play, 1)

        self.btn_pause = QPushButton("⏸  暂停  F8")
        self.btn_pause.setObjectName("btnPause")
        self.btn_pause.setMinimumHeight(40)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setToolTip("暂停/继续当前的录制或回放")
        self.btn_pause.clicked.connect(self._toggle_pause)
        row1.addWidget(self.btn_pause, 1)

        self.btn_insert = QPushButton("⏺  插入录制  F7")
        self.btn_insert.setObjectName("btnInsert")
        self.btn_insert.setMinimumHeight(40)
        self.btn_insert.setToolTip(
            "回放暂停期间：录制一段新操作，插入到暂停位置；恢复回放后先执行插入的动作"
        )
        self.btn_insert.clicked.connect(self._toggle_insert_record)
        row1.addWidget(self.btn_insert, 1)

        self.btn_stop = QPushButton("■  紧急停止  F12")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.clicked.connect(self._emergency_stop)
        row1.addWidget(self.btn_stop, 1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        speed_label = QLabel("回放速度")
        speed_label.setObjectName("subLabel")
        row2.addWidget(speed_label)
        self.speed_combo = QComboBox()
        for label, val in [("0.5x（慢速）", 0.5), ("1x（原速）", 1.0),
                           ("1.5x", 1.5), ("2x（快速）", 2.0), ("4x", 4.0)]:
            self.speed_combo.addItem(label, val)
        self.speed_combo.setCurrentIndex(1)
        row2.addWidget(self.speed_combo)

        loop_label = QLabel("循环次数")
        loop_label.setObjectName("subLabel")
        row2.addWidget(loop_label)
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 999)
        self.loop_spin.setValue(1)
        self.loop_spin.setMinimumWidth(70)
        row2.addWidget(self.loop_spin)

        self.chk_move = QCheckBox("录制鼠标移动轨迹")
        self.chk_move.setChecked(True)
        self.chk_move.stateChanged.connect(
            lambda st: setattr(self.recorder, "_record_mouse_move", st == Qt.Checked)
        )
        row2.addWidget(self.chk_move)

        row2.addStretch(1)

        b_export = QPushButton("导出 JSON")
        b_export.clicked.connect(self._on_export)
        row2.addWidget(b_export)

        b_clear = QPushButton("清空事件")
        b_clear.clicked.connect(self._on_clear_events)
        row2.addWidget(b_clear)
        lay.addLayout(row2)
        return panel

    def _init_status_bar(self):
        sb = self.statusBar()
        left = QWidget()
        h = QHBoxLayout(left)
        h.setContentsMargins(8, 0, 0, 0)
        h.setSpacing(6)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        h.addWidget(self.status_dot)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("subLabel")
        h.addWidget(self.status_label)
        h.addStretch(1)
        sb.addWidget(left, 1)

        self.script_info_label = QLabel("未选择脚本")
        self.script_info_label.setObjectName("subLabel")
        sb.addPermanentWidget(self.script_info_label)

        self._set_status("就绪 — F9 录制 / F10 回放 / F8 暂停 / F12 停止", "idle")

    def _set_status(self, text: str, state: str = "idle"):
        color = STATE_COLORS.get(state, STATE_COLORS["idle"])
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        self.status_label.setText(text)

    def _update_script_info(self):
        s = self.current_script
        if s is not None:
            self.script_info_label.setText(f"当前脚本：{s.name} · {len(s.events)} 条事件")
        else:
            self.script_info_label.setText("未选择脚本")

    def _set_btn_active(self, btn: QPushButton, active: bool):
        btn.setProperty("active", active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    # ---------- 信号连接 ----------

    def _connect_signals(self):
        self.signals.event_recorded.connect(self._on_event_ui)
        self.signals.hotkey_pressed.connect(self._on_hotkey_ui)
        self.signals.play_progress.connect(self._on_progress_ui)
        self.signals.play_finished.connect(self._on_finished_ui)

    # pynput 线程 -> Qt 信号（只做转发）
    def _on_event_threadsafe(self, ev: RecordedEvent):
        self.signals.event_recorded.emit(ev)

    def _on_hotkey_threadsafe(self, name: str):
        self.signals.hotkey_pressed.emit(name)

    def _on_progress_threadsafe(self, done: int, total: int):
        self.signals.play_progress.emit(done, total)

    def _on_finished_threadsafe(self, stopped: bool):
        self.signals.play_finished.emit(stopped)

    # ---------- 脚本管理 ----------

    def _load_scripts(self):
        self.scripts = self.storage.load_all()
        self._refresh_script_list()

    def _refresh_script_list(self, select: Script | None = None):
        self.script_list.blockSignals(True)
        self.script_list.clear()
        for s in self.scripts:
            item = QListWidgetItem(f"{s.name}    {len(s.events)} 条")
            item.setData(Qt.UserRole, s)
            self.script_list.addItem(item)
        self.script_list.blockSignals(False)
        if select is not None:
            for i in range(self.script_list.count()):
                if self.script_list.item(i).data(Qt.UserRole) is select:
                    self.script_list.setCurrentRow(i)
                    return
        if select is None and self.script_list.count() > 0:
            self.script_list.setCurrentRow(0)

    def _on_script_selected(self):
        item = self.script_list.currentItem()
        if item is None:
            self.current_script = None
            self._update_script_info()
            return
        s: Script = item.data(Qt.UserRole)
        self.current_script = s
        self._update_script_info()
        self._render_timeline(s.events)

    def _on_new_script(self):
        if self.recorder.recording or self.player.playing:
            self._busy_warning()
            return
        name, ok = QInputDialog.getText(self, "新建脚本", "脚本名称：", text="新脚本")
        if not ok or not name.strip():
            return
        s = Script(name.strip(), events=[])
        self.scripts.insert(0, s)
        self.storage.save(s)
        self._refresh_script_list(select=s)

    def _on_rename_script(self):
        s = self.current_script
        if s is None:
            return
        name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=s.name)
        if not ok or not name.strip():
            return
        old_path = self.storage._path(s)
        s.name = name.strip()
        self.storage.save(s)
        if os.path.exists(old_path) and old_path != self.storage._path(s):
            os.remove(old_path)
        self._refresh_script_list(select=s)
        self._update_script_info()

    def _on_delete_script(self):
        s = self.current_script
        if s is None:
            return
        if self.recorder.recording or self.player.playing:
            self._busy_warning()
            return
        ret = QMessageBox.question(
            self, "删除脚本", f"确定删除脚本「{s.name}」？此操作不可恢复。"
        )
        if ret != QMessageBox.Yes:
            return
        self.storage.delete(s)
        self.scripts.remove(s)
        self.current_script = None
        self._refresh_script_list()
        self._update_script_info()

    # ---------- 时间线渲染 ----------

    def _render_timeline(self, events: list[RecordedEvent]):
        self.event_table.setRowCount(0)
        if not events:
            self.timeline_stack.setCurrentWidget(self.hint_page)
            self.count_label.setText("0 条事件")
            return
        self._append_table_rows(events)
        total = len(events)
        if total > MAX_DISPLAY_ROWS:
            self.count_label.setText(f"{total} 条事件（仅显示前 {MAX_DISPLAY_ROWS} 条）")
        else:
            self.count_label.setText(f"{total} 条事件")

    def _append_table_rows(self, events: list[RecordedEvent]):
        table = self.event_table
        if self.timeline_stack.currentWidget() is not table:
            self.timeline_stack.setCurrentWidget(table)
        start = table.rowCount()
        if start >= MAX_DISPLAY_ROWS:
            return
        n = min(len(events), MAX_DISPLAY_ROWS - start)
        table.setUpdatesEnabled(False)
        table.setRowCount(start + n)
        for i, ev in enumerate(events[:n]):
            row = start + i
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setForeground(QColor("#9CA3AF"))
            table.setItem(row, 0, idx_item)

            t_item = QTableWidgetItem(f"{ev.timestamp:.2f}s")
            t_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t_item.setForeground(QColor("#6B7280"))
            table.setItem(row, 1, t_item)

            type_item = QTableWidgetItem(ev.type_label())
            type_item.setForeground(QColor(TYPE_COLORS.get(ev.event_type, "#1F2329")))
            table.setItem(row, 2, type_item)

            table.setItem(row, 3, QTableWidgetItem(ev.detail_text()))
        table.setUpdatesEnabled(True)
        table.scrollToBottom()

    def _on_event_ui(self, ev: RecordedEvent):
        """录制中事件到达（主线程），先入缓冲队列。"""
        self._pending_events.append(ev)

    def _flush_pending_events(self):
        if not self._pending_events:
            return
        rows = self._pending_events
        self._pending_events = []
        if self._insert_mode:
            # 插入录制：事件尚未确定插入位置，不追加到时间线表格，只更新计数
            self._insert_count += len(rows)
            self.count_label.setText(f"插入录制中：{self._insert_count} 条事件")
            return
        self._append_table_rows(rows)
        self._recorded_count += len(rows)
        self.count_label.setText(f"{self._recorded_count} 条事件（录制中）")

    # ---------- 录制控制 ----------

    def _toggle_record(self):
        if self._insert_mode:
            self._set_status("插入录制中 — 按 F7 结束插入", "recording")
            return
        if self.player.playing:
            self._set_status("回放进行中，无法录制", "playing")
            return
        if self.recorder.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        # 每次录制创建新脚本
        name = "录制 " + datetime.now().strftime("%m-%d %H%M%S")
        script = Script(name, events=[])
        self.current_script = script
        self.scripts.insert(0, script)
        self._refresh_script_list(select=script)

        self.event_table.setRowCount(0)
        self._pending_events.clear()
        self._recorded_count = 0
        self.timeline_stack.setCurrentWidget(self.event_table)
        self.count_label.setText("0 条事件（录制中）")

        self.recorder.start_recording()
        self._flush_timer.start()

        self.btn_record.setText("■  停止录制  F9")
        self._set_btn_active(self.btn_record, True)
        self.btn_pause.setEnabled(True)
        self._set_status("录制中… 按 F9 结束，F8 暂停", "recording")
        self._update_script_info()
        self._enter_mini("recording")

    def _stop_recording(self):
        events = self.recorder.stop_recording()
        self._flush_timer.stop()
        self._flush_pending_events()
        if self.current_script is not None:
            self.current_script.events = events
            if events:
                self.storage.save(self.current_script)
        self._refresh_script_list(select=self.current_script)
        self._render_timeline(events)

        self.btn_record.setText("●  开始录制  F9")
        self._set_btn_active(self.btn_record, False)
        self._reset_pause_button()
        self._set_status(
            f"录制完成，共 {len(events)} 条事件" + ("" if events else "（未录到任何操作）"),
            "idle",
        )
        self._update_script_info()
        self._exit_mini()

    # ---------- 回放控制 ----------

    def _toggle_play(self):
        if self._insert_mode:
            self._set_status("插入录制中 — 按 F7 结束插入", "recording")
            return
        if self.recorder.recording:
            self._set_status("录制进行中，无法回放", "recording")
            return
        if self.player.playing:
            self.player.stop()
            return
        s = self.current_script
        if s is None or not s.events:
            QMessageBox.information(self, "提示", "请先选择一个包含事件的脚本")
            return
        speed = self.speed_combo.currentData()
        loops = self.loop_spin.value()
        ok = self.player.play(s.events, speed=speed, loops=loops)
        if ok:
            self._last_progress = (0, len(s.events) * loops)
            self.btn_play.setText("■  停止回放  F10")
            self._set_btn_active(self.btn_play, True)
            self.btn_pause.setEnabled(True)
            self._set_status(
                f"回放中… {len(s.events)} 条 × {loops} 次 @ {speed}x（F8 暂停 / F10 停止）",
                "playing",
            )
            self._enter_mini("playing")

    def _on_progress_ui(self, done: int, total: int):
        self._last_progress = (done, total)
        if self.player.paused:
            return  # 暂停时保持暂停提示，不被进度刷新覆盖
        self._set_status(f"回放中… {done}/{total}（F8 暂停 / F10 停止）", "playing")

    def _on_finished_ui(self, stopped: bool):
        if self._insert_mode:
            # 回放意外结束：丢弃未完成的插入录制（正常流程插入期间回放始终暂停）
            self._cancel_insert_recording()
        self._last_progress = (0, 0)
        self._exit_mini()
        self.btn_play.setText("▶  开始回放  F10")
        self._set_btn_active(self.btn_play, False)
        self._reset_pause_button()
        self._set_status("回放已停止" if stopped else "回放完成", "idle")

    def _emergency_stop(self):
        if self._insert_mode:
            # 紧急停止 = 放弃一切：未完成的插入录制直接丢弃
            self._cancel_insert_recording()
        if self.recorder.recording:
            self._stop_recording()
        if self.player.playing:
            self.player.stop()
        self._exit_mini()
        self._reset_pause_button()
        self._set_status("已紧急停止", "idle")

    # ---------- 暂停 ----------

    def _toggle_pause(self):
        """F8：暂停/继续当前的录制或回放。"""
        if self._insert_mode:
            self._set_status("插入录制中 — 按 F7 结束插入后再继续回放", "recording")
            return
        if self.recorder.recording:
            if self.recorder.paused:
                self.recorder.resume_recording()
                self.btn_pause.setText("⏸  暂停  F8")
                self._set_btn_active(self.btn_pause, False)
                self.count_label.setText(f"{self._recorded_count} 条事件（录制中）")
                self._set_status("录制中… 按 F9 结束，F8 暂停", "recording")
            else:
                self.recorder.pause_recording()
                self.btn_pause.setText("▶  继续  F8")
                self._set_btn_active(self.btn_pause, True)
                self.count_label.setText(f"{self._recorded_count} 条事件（已暂停）")
                self._set_status("录制已暂停 — 按 F8 继续，F9 结束", "paused")
        elif self.player.playing:
            if self.player.paused:
                self.player.resume()
                self.btn_pause.setText("⏸  暂停  F8")
                self._set_btn_active(self.btn_pause, False)
                self._set_status("回放中…（F8 暂停 / F10 停止）", "playing")
            else:
                self.player.pause()
                self.btn_pause.setText("▶  继续  F8")
                self._set_btn_active(self.btn_pause, True)
                self._set_status("回放已暂停 — F8 继续 / F7 插入录制 / F10 停止", "paused")
        else:
            self._set_status("当前没有进行中的录制或回放", "idle")

    def _reset_pause_button(self):
        """把暂停按钮恢复为初始禁用状态。"""
        self.btn_pause.setText("⏸  暂停  F8")
        self._set_btn_active(self.btn_pause, False)
        self.btn_pause.setEnabled(False)

    # ---------- 插入录制（回放暂停期间） ----------

    def _toggle_insert_record(self):
        """F7：回放暂停期间，录制一段新操作插入到暂停位置。"""
        if self._insert_mode:
            self._finish_insert_recording()
            return
        if self.recorder.recording:
            self._set_status("正在录制中，无法插入录制（先按 F9 结束）", "recording")
            return
        if not self.player.playing:
            self._set_status("插入录制需先开始回放并按 F8 暂停", "idle")
            return
        if not self.player.paused:
            self._set_status("请先按 F8 暂停回放，再按 F7 插入录制", "playing")
            return
        self._start_insert_recording()

    def _start_insert_recording(self):
        """开始在回放暂停位置录制插入动作（回放保持暂停不终止）。"""
        self._insert_mode = True
        self._insert_count = 0
        self._pending_events.clear()
        self.recorder.start_recording()
        self._flush_timer.start()
        self._mini_mode = "insert"
        self._update_mini()

        self.btn_insert.setText("■  结束插入  F7")
        self._set_btn_active(self.btn_insert, True)
        # 插入录制期间锁定其余操作，保证插入位置语义明确
        self.btn_record.setEnabled(False)
        self.btn_play.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.script_list.setEnabled(False)
        self.count_label.setText("插入录制中：0 条事件")
        self._set_status("插入录制中… 动作将插入到回放暂停位置，按 F7 结束", "recording")

    def _finish_insert_recording(self):
        """结束插入录制：把录制的事件拼接进回放时间线并持久化到脚本。"""
        if not self._insert_mode:
            return
        events = self.recorder.stop_recording()
        self._flush_timer.stop()
        self._pending_events.clear()
        self._insert_mode = False
        self._restore_insert_ui()
        # 回放仍保持暂停，小窗切回回放状态
        self._mini_mode = "playing" if self.player.playing else None
        self._update_mini()

        merged = self.player.insert_at_pause(events)
        s = self.current_script
        if merged is None:
            # 回放已不在暂停状态：插入的事件退回为追加到脚本末尾，避免丢失
            if s is not None and events:
                base = s.events[-1].timestamp if s.events else 0.0
                seg = [
                    RecordedEvent(base + ev.timestamp, ev.event_type, dict(ev.data))
                    for ev in events
                ]
                s.events = s.events + seg
                self.storage.save(s)
                self._refresh_script_list(select=s)
                self._render_timeline(s.events)
                self._set_status("回放已结束，插入录制的事件已追加到脚本末尾", "idle")
            else:
                self._set_status("插入录制已取消" if not events else "未找到当前脚本，插入的事件已丢弃", "idle")
            return

        if s is None:
            self._set_status("未找到当前脚本，插入的事件已丢弃", "idle")
            return
        s.events = merged
        self.storage.save(s)
        self._refresh_script_list(select=s)
        self._render_timeline(merged)
        self._set_status(
            f"已插入 {len(events)} 条事件到回放暂停位置 — 按 F8 继续回放", "paused",
        )

    def _cancel_insert_recording(self):
        """放弃插入录制（紧急停止 / 回放意外结束时调用）。"""
        if not self._insert_mode:
            return
        self.recorder.stop_recording()
        self._flush_timer.stop()
        self._pending_events.clear()
        self._insert_mode = False
        self._restore_insert_ui()
        if self.player.playing:
            self._mini_mode = "playing"

    def _restore_insert_ui(self):
        """恢复插入录制期间锁定的 UI 控件。"""
        self.btn_insert.setText("⏺  插入录制  F7")
        self._set_btn_active(self.btn_insert, False)
        self.btn_record.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.script_list.setEnabled(True)

    # ---------- 悬浮小窗 ----------

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """秒数格式化为 mm:ss。"""
        s = max(0, int(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _enter_mini(self, mode: str):
        """隐藏主窗口，显示悬浮小窗。mode: recording / playing / insert。"""
        self._mini_mode = mode
        self.hide()
        self._update_mini()
        self.mini.show_at_default_position()
        self._mini_timer.start()

    def _exit_mini(self):
        """隐藏悬浮小窗，恢复主窗口。"""
        if self._mini_mode is None and not self.mini.isVisible():
            return
        self._mini_mode = None
        self._mini_timer.stop()
        self.mini.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _expand_from_mini(self):
        """小窗的 ▼/✕：恢复完整界面（当前录制/回放继续在后台运行）。"""
        self._mini_mode = None
        self._mini_timer.stop()
        self.mini.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_status("已展开完整界面 — 录制/回放仍在后台运行，热键有效", "idle")

    def _on_mini_stop(self):
        """小窗的停止按钮：停止当前的录制或回放。"""
        if self._insert_mode:
            # 先结束插入录制（拼接入时间线），再停止回放
            self._finish_insert_recording()
            if self.player.playing:
                self.player.stop()
            return
        if self.recorder.recording:
            self._toggle_record()
        elif self.player.playing:
            self.player.stop()

    def _update_mini(self):
        """根据当前模式刷新小窗内容。"""
        if self._mini_mode is None:
            return
        if self._mini_mode == "recording":
            paused = self.recorder.paused
            self.mini.set_state("录制已暂停" if paused else "录制中",
                                "#F59E0B" if paused else "#EF4444")
            self.mini.set_time(self._fmt_duration(self.recorder._now()))
            self.mini.set_count(f"事件数: {self._recorded_count + len(self._pending_events)}")
            self.mini.set_speed("")
            self.mini.set_pause_active(paused)
        elif self._mini_mode == "insert":
            self.mini.set_state("插入录制中", "#7C3AED")
            self.mini.set_time(self._fmt_duration(self.recorder._now()))
            self.mini.set_count(f"事件数: {self._insert_count + len(self._pending_events)}")
            self.mini.set_speed("")
            self.mini.set_pause_active(False)
        elif self._mini_mode == "playing":
            paused = self.player.paused
            self.mini.set_state("回放已暂停" if paused else "回放中",
                                "#F59E0B" if paused else "#3B82F6")
            pos = self.player.position_time
            dur = self.player.total_duration
            self.mini.set_time(f"{pos:.1f}s / {dur:.1f}s")
            done, total = self._last_progress
            self.mini.set_count(f"事件数: {done}/{total}" if total else "事件数: 0")
            speed = self.speed_combo.currentData()
            self.mini.set_speed(f"回放速度: {speed:g}x")
            self.mini.set_pause_active(paused)

    # ---------- 热键 ----------

    def _on_hotkey_ui(self, name: str):
        if name == "toggle_record":
            self._toggle_record()
        elif name == "toggle_play":
            self._toggle_play()
        elif name == "toggle_pause":
            self._toggle_pause()
        elif name == "insert_record":
            self._toggle_insert_record()
        elif name == "emergency_stop":
            self._emergency_stop()

    # ---------- 其他 ----------

    def _on_export(self):
        s = self.current_script
        if s is None or not s.events:
            QMessageBox.information(self, "提示", "当前脚本没有可导出的事件")
            return
        default = f"{s.name}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 JSON", default, "JSON 文件 (*.json)"
        )
        if path:
            self.storage.export_json(s, path)
            self._set_status(f"已导出到 {path}", "idle")

    def _on_clear_events(self):
        s = self.current_script
        if s is None:
            return
        if self.recorder.recording or self.player.playing:
            self._busy_warning()
            return
        ret = QMessageBox.question(self, "清空事件", f"清空脚本「{s.name}」的全部事件？")
        if ret != QMessageBox.Yes:
            return
        s.events = []
        self.storage.save(s)
        self._render_timeline([])
        self._refresh_script_list(select=s)
        self._update_script_info()

    def _busy_warning(self):
        QMessageBox.warning(self, "提示", "录制/回放进行中，请先停止后再操作")

    def closeEvent(self, event):
        # 录制中途关闭窗口：把已录的事件保存下来，避免数据丢失
        if self.recorder.recording:
            events = self.recorder.stop_recording()
            self._flush_timer.stop()
            self._flush_pending_events()
            if self.current_script is not None and events:
                self.current_script.events = events
                self.storage.save(self.current_script)
        # 插入录制中途关闭：同样落盘（追加到脚本末尾）
        elif self._insert_mode:
            events = self.recorder.stop_recording()
            self._flush_timer.stop()
            self._pending_events.clear()
            self._insert_mode = False
            s = self.current_script
            if s is not None and events:
                base = s.events[-1].timestamp if s.events else 0.0
                seg = [
                    RecordedEvent(base + ev.timestamp, ev.event_type, dict(ev.data))
                    for ev in events
                ]
                s.events = s.events + seg
                self.storage.save(s)
        self.recorder.stop_listening()
        self.player.stop()
        self.mini.close()
        event.accept()
