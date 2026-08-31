"""简略版事件时间线：横向时间轴视图。

把连续同类型的事件合并为一张卡片，按时间横向排布：
- 合并规则：连续同类型且"动作签名"相同的事件合并为一组
  （移动合并所有连续移动；滚轮按方向合并；点击按 按键+按下/释放 合并；
  键盘按 键名+按下/释放 合并）
- 顶部时间刻度尺：刻度间隔随缩放自适应（0.1s ~ 300s）
- 事件卡片固定尺寸，按泳道（lane）错层排布避免重叠
- 缩放控件：- / + / 适配窗口；底部滑块显示密度与视口位置，
  拖拽滑块 / 点击轨道 / 滚轮（Shift+滚轮）控制视口左右移动
- 回放位置标记：蓝色竖线 + 时间标签，由外部 position_provider 驱动刷新
"""

from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QFont
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame,
)

from event_types import (
    RecordedEvent, EV_MOUSE_CLICK, EV_MOUSE_MOVE, EV_MOUSE_SCROLL,
    EV_KEY_PRESS, EV_KEY_RELEASE, TYPE_LABELS, BTN_NAMES,
)

# ---------- 视觉常量 ----------

GROUP_COLORS = {
    EV_MOUSE_CLICK: "#2563EB",
    EV_MOUSE_MOVE: "#0D9488",
    EV_MOUSE_SCROLL: "#D97706",
    EV_KEY_PRESS: "#7C3AED",
    EV_KEY_RELEASE: "#7C3AED",
}

GROUP_ICONS = {
    EV_MOUSE_CLICK: "击",
    EV_MOUSE_MOVE: "移",
    EV_MOUSE_SCROLL: "滚",
    EV_KEY_PRESS: "按",
    EV_KEY_RELEASE: "放",
}

BASE_PX_PER_SEC = 80.0      # 100% 缩放对应的像素/秒
MIN_PX_PER_SEC = 2.0
MAX_PX_PER_SEC = 1200.0

RULER_H = 48                # 刻度尺高度
CARD_W = 132                # 卡片固定宽度
CARD_H = 62                 # 卡片固定高度
LANE_GAP = 10               # 泳道间距
LEFT_PAD = 16
RIGHT_PAD = 80
CARD_X_GAP = 8              # 同泳道相邻卡片最小水平间距


def _fmt_time(t: float) -> str:
    """秒 → mm:ss.mmm（分钟可超过 59）。"""
    t = max(0.0, t)
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:06.3f}"


def _fmt_duration(t: float) -> str:
    """秒 → 统计时长格式：mm:ss.mmm，超 1 小时为 hh:mm:ss。"""
    t = max(0.0, t)
    if t >= 3600:
        h = int(t // 3600)
        m = int((t - h * 3600) // 60)
        s = t - h * 3600 - m * 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return _fmt_time(t)


def _sign(v) -> int:
    return (v > 0) - (v < 0)


# ---------- 合并 ----------

class EventGroup:
    """一组连续同类型事件的合并结果。"""

    __slots__ = ("event_type", "signature", "events", "start_time", "end_time", "lane")

    def __init__(self, ev: RecordedEvent):
        self.event_type = ev.event_type
        self.signature = self._signature_of(ev)
        self.events = [ev]
        self.start_time = ev.timestamp
        self.end_time = ev.timestamp
        self.lane = 0

    @staticmethod
    def _signature_of(ev: RecordedEvent):
        """动作签名：只有签名相同的连续事件才合并。"""
        d = ev.data
        et = ev.event_type
        if et == EV_MOUSE_CLICK:
            return (d.get("button"), bool(d.get("pressed")))
        if et in (EV_KEY_PRESS, EV_KEY_RELEASE):
            return d.get("key", "")
        if et == EV_MOUSE_SCROLL:
            return (_sign(d.get("dx", 0)), _sign(d.get("dy", 0)))
        return None  # mouse_move：所有连续移动都合并

    def can_absorb(self, ev: RecordedEvent) -> bool:
        return (
            ev.event_type == self.event_type
            and self._signature_of(ev) == self.signature
        )

    def absorb(self, ev: RecordedEvent):
        self.events.append(ev)
        self.end_time = ev.timestamp

    @property
    def count(self) -> int:
        return len(self.events)

    # ---------- 卡片文案 ----------

    def title(self) -> str:
        label = TYPE_LABELS.get(self.event_type, self.event_type)
        return label if self.count == 1 else f"{label} ×{self.count}"

    def detail(self) -> str:
        first, last = self.events[0], self.events[-1]
        d = first.data
        et = self.event_type
        if et == EV_MOUSE_MOVE:
            if self.count == 1:
                return f"({d.get('x')}, {d.get('y')})"
            return f"({d.get('x')}, {d.get('y')}) → ({last.data.get('x')}, {last.data.get('y')})"
        if et == EV_MOUSE_CLICK:
            action = "按下" if d.get("pressed") else "释放"
            btn = BTN_NAMES.get(d.get("button"), d.get("button", "?"))
            return f"{action}{btn}键 ({d.get('x')}, {d.get('y')})"
        if et == EV_MOUSE_SCROLL:
            direction = "上" if d.get("dy", 0) > 0 else "下"
            total = sum(abs(e.data.get("dy", 0)) for e in self.events)
            return f"向{direction}共 {total:g} 格"
        if et in (EV_KEY_PRESS, EV_KEY_RELEASE):
            return first._key_display()
        return ""

    def time_text(self) -> str:
        if self.count == 1 or self.end_time - self.start_time < 0.001:
            return _fmt_time(self.start_time)
        return f"{_fmt_time(self.start_time)} → {_fmt_time(self.end_time)}"


def merge_events(events: list[RecordedEvent]) -> list[EventGroup]:
    """把事件列表合并为分组列表。"""
    groups: list[EventGroup] = []
    for ev in events:
        if groups and groups[-1].can_absorb(ev):
            groups[-1].absorb(ev)
        else:
            groups.append(EventGroup(ev))
    return groups


# ---------- 画布 ----------

class _TimelineCanvas(QWidget):
    """时间轴画布：刻度尺 + 泳道卡片 + 位置标记（QPainter 自绘）。"""

    def __init__(self, view: "SimpleTimelineWidget"):
        super().__init__()
        self.view = view

    def wheelEvent(self, e):
        # 横向时间轴没有纵向滚动：滚轮（含 Shift+滚轮）直接控制左右移动。
        # 部分系统在 Shift 下把滚轮报到 x 分量，两个都兼容。
        delta = e.angleDelta()
        steps = -(delta.y() or delta.x()) / 120
        self.view.nudge_scroll(steps)
        e.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        v = self.view
        if not v.groups:
            p.setPen(QColor("#9CA3AF"))
            p.setFont(QFont("Microsoft YaHei", 12))
            p.drawText(self.rect(), Qt.AlignCenter, "暂无事件")
            return
        v.paint_ruler(p)
        v.paint_groups(p)
        v.paint_marker(p)


class _SliderBar(QWidget):
    """底部滑块：事件密度轨道 + 可拖拽滑块，控制画布横向滚动。

    - 滑块宽度 ∝ 视口/内容宽度，位置对应当前滚动位置
    - 拖拽滑块：视口跟随左右移动；点击轨道：视口跳到点击处（按住可继续拖）
    - 滚轮 / Shift+滚轮：按视口比例步进滚动
    """

    THUMB_MIN_W = 28.0

    def __init__(self, view: "SimpleTimelineWidget"):
        super().__init__()
        self.view = view
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)
        self._drag_offset: float | None = None  # 拖拽中：抓取点相对滑块左缘的偏移

    # ---------- 几何换算 ----------

    def _thumb_rect(self) -> QRectF:
        """滑块当前矩形（轨道坐标系）。"""
        v = self.view
        w = self.width()
        cw = v.canvas.width()
        vw = v.scroll.viewport().width()
        if cw <= 0 or vw >= cw:
            # 内容未超出视口：滑块占满轨道（不可滚动）
            return QRectF(1, 3, max(w - 2, 1), self.height() - 6)
        track = w - 2
        thumb_w = max(self.THUMB_MIN_W, vw / cw * track)
        sb = v.scroll.horizontalScrollBar()
        frac = sb.value() / max(1, sb.maximum())
        x = 1 + frac * (track - thumb_w)
        return QRectF(x, 3, thumb_w, self.height() - 6)

    def _set_viewport_frac(self, frac: float):
        """把视口左缘设置到轨道比例 frac（0~1）处。"""
        sb = self.view.scroll.horizontalScrollBar()
        sb.setValue(int(max(0.0, min(1.0, frac)) * sb.maximum()))

    def _frac_for_thumb_left(self, x: float) -> float:
        """滑块左缘 x → 轨道比例。"""
        track = self.width() - 2
        thumb_w = self._thumb_rect().width()
        if track <= thumb_w:
            return 0.0
        return (x - 1) / (track - thumb_w)

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 轨道背景
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.setBrush(QColor("#F4F5F7"))
        p.drawRoundedRect(QRectF(0.5, 2.5, w - 1, h - 3.5), 6, 6)
        # 事件密度刻度
        v = self.view
        dur = v.duration
        if dur > 0:
            p.setPen(QPen(QColor("#93C5FD"), 2))
            for g in v.groups:
                x = int(g.start_time / dur * (w - 4)) + 2
                p.drawLine(x, 6, x, h - 6)
        # 滑块
        thumb = self._thumb_rect()
        p.setPen(QPen(QColor("#2563EB"), 1.2))
        p.setBrush(QColor(37, 99, 235, 46))
        p.drawRoundedRect(thumb, 6, 6)
        # 握把纹（三条竖线，提示可拖拽）
        if thumb.width() >= 24:
            cx = thumb.center().x()
            cy = thumb.center().y()
            p.setPen(QPen(QColor("#2563EB"), 1.4))
            for dx in (-5, 0, 5):
                p.drawLine(int(cx + dx), int(cy - 4), int(cx + dx), int(cy + 4))

    # ---------- 交互 ----------

    def mousePressEvent(self, e):
        thumb = self._thumb_rect()
        if thumb.contains(e.localPos()):
            # 抓住滑块：记录抓取偏移，拖拽时视口跟随
            self._drag_offset = e.localPos().x() - thumb.x()
        else:
            # 点击轨道：视口中心跳到点击处，并进入拖拽状态（按住即可继续拖）
            self._drag_offset = thumb.width() / 2
            self._set_viewport_frac(
                self._frac_for_thumb_left(e.localPos().x() - self._drag_offset)
            )
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag_offset is None:
            return
        self._set_viewport_frac(
            self._frac_for_thumb_left(e.localPos().x() - self._drag_offset)
        )

    def mouseReleaseEvent(self, e):
        self._drag_offset = None

    def wheelEvent(self, e):
        delta = e.angleDelta()
        steps = -(delta.y() or delta.x()) / 120
        self.view.nudge_scroll(steps)
        e.accept()


# ---------- 主视图 ----------

class SimpleTimelineWidget(QWidget):
    """简略版横向时间线（自包含：头部统计 + 缩放控件 + 滚动画布 + 底部滑块）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: list[EventGroup] = []
        self.px_per_sec = BASE_PX_PER_SEC
        self._lane_ends: list[float] = []   # 每条泳道当前最右端 x
        self._position: float | None = None  # 回放位置标记（秒）
        self._fit_mode = False
        self.position_provider = None        # callable -> float | None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # 头部：统计 + 缩放控件
        header = QHBoxLayout()
        header.setContentsMargins(2, 2, 2, 0)
        header.setSpacing(8)
        self.stats_label = QLabel("总事件: 0 条    总时长: 00:00.000")
        self.stats_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        header.addWidget(self.stats_label)
        header.addStretch(1)

        zoom_label = QLabel("缩放")
        zoom_label.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        header.addWidget(zoom_label)
        btn_style = (
            "QPushButton { border: 1px solid #D9DCE1; border-radius: 6px; background: #FFFFFF;"
            " min-width: 26px; max-width: 26px; min-height: 24px; max-height: 24px; padding: 0; }"
            "QPushButton:hover { background: #F3F4F6; }"
        )
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setStyleSheet(btn_style)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        header.addWidget(self.btn_zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: #4B5563; font-size: 12px;")
        self.zoom_label.setMinimumWidth(42)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.zoom_label)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setStyleSheet(btn_style)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        header.addWidget(self.btn_zoom_in)
        self.btn_fit = QPushButton("适配窗口")
        self.btn_fit.setStyleSheet(
            "QPushButton { border: 1px solid #D9DCE1; border-radius: 6px; background: #FFFFFF;"
            " min-height: 24px; max-height: 24px; padding: 0 10px; font-size: 12px; color: #4B5563; }"
            "QPushButton:hover { background: #F3F4F6; }"
        )
        self.btn_fit.clicked.connect(self.fit_window)
        header.addWidget(self.btn_fit)
        root.addLayout(header)

        # 滚动画布
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = _TimelineCanvas(self)
        self.canvas.setFixedSize(600, RULER_H + CARD_H + 20)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        # 底部滑块（拖拽/滚轮控制视口滚动）
        self.slider = _SliderBar(self)
        root.addWidget(self.slider)
        self.scroll.horizontalScrollBar().valueChanged.connect(self.slider.update)

        # 位置标记刷新（回放中由 position_provider 驱动）
        self._marker_timer = QTimer(self)
        self._marker_timer.setInterval(120)
        self._marker_timer.timeout.connect(self._poll_position)
        self._marker_timer.start()

    # ---------- 数据 ----------

    @property
    def duration(self) -> float:
        return self.groups[-1].end_time if self.groups else 0.0

    def set_events(self, events: list[RecordedEvent]):
        """全量设置事件（重新合并 + 布局）。"""
        self.groups = merge_events(events)
        self._relayout(full=True)

    def append_events(self, events: list[RecordedEvent]):
        """增量追加事件（录制中持续调用，只布局新增分组）。"""
        if not events:
            return
        old_count = len(self.groups)
        for ev in events:
            if self.groups and self.groups[-1].can_absorb(ev):
                self.groups[-1].absorb(ev)
            else:
                self.groups.append(EventGroup(ev))
        self._relayout(full=False, from_index=old_count)

    def clear(self):
        self.groups = []
        self._position = None
        self._relayout(full=True)

    # ---------- 布局 ----------

    def _relayout(self, full: bool, from_index: int = 0):
        if full:
            # 缩放变化时所有卡片 x 都变，泳道必须全量重排
            self._lane_ends = []
            from_index = 0
        # 泳道分配：增量时只处理新增分组（已有分组的 x 不变，泳道分配保持有效）
        for g in self.groups[from_index:]:
            x = LEFT_PAD + g.start_time * self.px_per_sec
            placed = False
            for i, end_x in enumerate(self._lane_ends):
                if x >= end_x + CARD_X_GAP:
                    g.lane = i
                    self._lane_ends[i] = x + CARD_W
                    placed = True
                    break
            if not placed:
                g.lane = len(self._lane_ends)
                self._lane_ends.append(x + CARD_W)

        lanes = max(1, len(self._lane_ends))
        content_w = LEFT_PAD + self.duration * self.px_per_sec + RIGHT_PAD
        vp_w = self.scroll.viewport().width()
        w = max(int(content_w), vp_w)
        h = RULER_H + lanes * (CARD_H + LANE_GAP) + 12
        self.canvas.setFixedSize(w, h)
        total = sum(g.count for g in self.groups)
        self.stats_label.setText(
            f"总事件: {total} 条（合并为 {len(self.groups)} 组）    总时长: {_fmt_duration(self.duration)}"
        )
        self.canvas.update()
        self.slider.update()

    # ---------- 滚动 ----------

    def nudge_scroll(self, steps: float):
        """按视口宽度比例横向滚动。steps 为滚轮格数（正=向右）。"""
        sb = self.scroll.horizontalScrollBar()
        if sb.maximum() <= 0:
            return
        vw = self.scroll.viewport().width()
        delta = int(steps * vw * 0.15)  # 每格滚 15% 视口宽度
        sb.setValue(max(0, min(sb.value() + delta, sb.maximum())))

    # ---------- 缩放 ----------

    def _set_zoom(self, px: float):
        self.px_per_sec = max(MIN_PX_PER_SEC, min(MAX_PX_PER_SEC, px))
        pct = round(self.px_per_sec / BASE_PX_PER_SEC * 100)
        self.zoom_label.setText(f"{pct}%")
        self._relayout(full=True)

    def zoom_in(self):
        self._fit_mode = False
        self._set_zoom(self.px_per_sec * 1.25)

    def zoom_out(self):
        self._fit_mode = False
        self._set_zoom(self.px_per_sec / 1.25)

    def fit_window(self):
        dur = self.duration
        if dur <= 0:
            return
        self._fit_mode = True
        vp_w = self.scroll.viewport().width()
        px = (vp_w - LEFT_PAD - RIGHT_PAD) / dur
        self._set_zoom(px)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit_mode and self.duration > 0:
            vp_w = self.scroll.viewport().width()
            self.px_per_sec = max(
                MIN_PX_PER_SEC,
                min(MAX_PX_PER_SEC, (vp_w - LEFT_PAD - RIGHT_PAD) / self.duration),
            )
            self._relayout(full=True)

    # ---------- 位置标记 ----------

    def set_position(self, seconds: float | None):
        """设置回放位置标记（秒），None 隐藏。"""
        if seconds != self._position:
            self._position = seconds
            self.canvas.update()

    def _poll_position(self):
        if self.position_provider is None:
            return
        try:
            self.set_position(self.position_provider())
        except Exception:
            pass

    # ---------- 绘制 ----------

    def paint_ruler(self, p: QPainter):
        w = self.canvas.width()
        # 刻度间隔：目标间距 ≥ 70px
        interval = 600.0
        for cand in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
            if cand * self.px_per_sec >= 70:
                interval = cand
                break
        base_y = RULER_H - 10
        p.setPen(QPen(QColor("#E5E7EB"), 1))
        p.drawLine(0, base_y, w, base_y)
        p.setFont(QFont("Microsoft YaHei", 8))
        t = 0.0
        dur = self.duration
        while t <= dur + interval * 0.5:
            x = LEFT_PAD + t * self.px_per_sec
            if x > w:
                break
            p.setPen(QPen(QColor("#D1D5DB"), 1))
            p.drawLine(int(x), base_y - 6, int(x), base_y)
            p.setPen(QColor("#6B7280"))
            p.drawText(QRectF(x - 40, 4, 80, 14), Qt.AlignCenter, _fmt_time(t))
            t += interval

    def paint_groups(self, p: QPainter):
        base_y = RULER_H - 10
        for g in self.groups:
            x = LEFT_PAD + g.start_time * self.px_per_sec
            y = RULER_H + g.lane * (CARD_H + LANE_GAP)
            color = QColor(GROUP_COLORS.get(g.event_type, "#1F2329"))
            # 连接线：刻度尺上的圆点 + 到卡片的竖线
            p.setPen(QPen(QColor("#D1D5DB"), 1))
            p.drawLine(int(x), base_y, int(x), int(y))
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(x - 3, base_y - 3, 6, 6))
            # 卡片
            card = QRectF(x, y, CARD_W, CARD_H)
            p.setPen(QPen(QColor("#E5E7EB"), 1))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(card, 8, 8)
            # 图标圆
            icon_rect = QRectF(x + 8, y + 8, 22, 22)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawEllipse(icon_rect)
            p.setPen(QColor("#FFFFFF"))
            f = QFont("Microsoft YaHei", 9)
            f.setBold(True)
            p.setFont(f)
            p.drawText(icon_rect, Qt.AlignCenter, GROUP_ICONS.get(g.event_type, "?"))
            # 标题
            p.setPen(QColor("#1F2329"))
            f2 = QFont("Microsoft YaHei", 10)
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(QRectF(x + 36, y + 8, CARD_W - 42, 20),
                       Qt.AlignLeft | Qt.AlignVCenter, g.title())
            # 详情
            p.setPen(QColor("#6B7280"))
            p.setFont(QFont("Microsoft YaHei", 8))
            detail = g.detail()
            metrics = p.fontMetrics()
            detail = metrics.elidedText(detail, Qt.ElideRight, CARD_W - 20)
            p.drawText(QRectF(x + 10, y + 32, CARD_W - 20, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, detail)
            # 时间
            p.setPen(QColor("#9CA3AF"))
            time_text = metrics.elidedText(g.time_text(), Qt.ElideRight, CARD_W - 20)
            p.drawText(QRectF(x + 10, y + 46, CARD_W - 20, 13),
                       Qt.AlignLeft | Qt.AlignVCenter, time_text)

    def paint_marker(self, p: QPainter):
        if self._position is None or not self.groups:
            return
        x = LEFT_PAD + self._position * self.px_per_sec
        h = self.canvas.height()
        p.setPen(QPen(QColor("#2563EB"), 1.5))
        p.drawLine(int(x), 18, int(x), h - 4)
        # 时间标签
        label = _fmt_time(self._position)
        p.setFont(QFont("Microsoft YaHei", 8))
        tw = p.fontMetrics().horizontalAdvance(label) + 12
        bx = min(max(x - tw / 2, 2), self.canvas.width() - tw - 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2563EB"))
        p.drawRoundedRect(QRectF(bx, 2, tw, 15), 4, 4)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(bx, 2, tw, 15), Qt.AlignCenter, label)
