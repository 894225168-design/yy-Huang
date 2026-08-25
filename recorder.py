"""录制模块：使用 pynput 捕获鼠标和键盘事件。

设计要点：
- 键盘监听器常驻运行，同时承担「全局热键检测」和「录制按键事件」两个职责。
- 鼠标监听器仅在录制期间启动，使用高精度子类（滚轮增量浮点化）。
- 所有回调都在 pynput 的监听线程中执行，UI 更新需要通过信号机制回到主线程。
- 录制鼠标事件时附带当前修饰键状态（mods），供回放端做双保险。
"""

import ctypes
import threading
import time
from typing import Callable, Optional

from pynput import keyboard, mouse

from event_types import (
    EV_KEY_PRESS, EV_KEY_RELEASE, EV_MOUSE_CLICK, EV_MOUSE_MOVE, EV_MOUSE_SCROLL,
    MODIFIER_KEY_NAMES, RecordedEvent, key_to_str,
)

# 高精度滚轮监听器依赖的 pynput 内部模块（不可用时回退标准监听器）
try:
    from pynput._util.win32 import SystemHook, wintypes
    from pynput.mouse._win32 import WHEEL_DELTA
    _PRECISION_SCROLL_AVAILABLE = True
except Exception:
    _PRECISION_SCROLL_AVAILABLE = False


def ensure_dpi_awareness() -> None:
    """把进程标记为 DPI 感知。

    高分屏（125%/150% 缩放）下，非 DPI 感知进程拿到的是虚拟化坐标，
    会导致录制坐标与回放坐标系不一致、点击位置偏移。
    应用启动时调用一次即可。
    """
    try:
        # Windows 10 1703+：Per-Monitor V2（-4）
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        # Vista+：Per-Monitor（2）
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


if _PRECISION_SCROLL_AVAILABLE:
    class PrecisionMouseListener(mouse.Listener):
        """修复 pynput 滚轮增量的整除截断问题。

        pynput 原版用 `delta // 120` 整除计算格数，高精度触摸板的部分增量
        （如 60，即半格）会被截断为 0；这里改为浮点除法保留部分增量。
        """

        def _handle_message(self, code, msg, lpdata):
            if code != SystemHook.HC_ACTION:
                return
            data = ctypes.cast(lpdata, self._LPMSLLHOOKSTRUCT).contents
            injected = (
                data.flags
                & (
                    self._MSLLHOOKSTRUCT.LLMHF_INJECTED
                    | self._MSLLHOOKSTRUCT.LLMHF_LOWER_IL_INJECTED
                )
            ) != 0
            if self._event_filter(msg, data) is False:
                return

            if msg == self.WM_MOUSEMOVE:
                self.on_move(data.pt.x, data.pt.y, injected)
            elif msg in self.CLICK_BUTTONS:
                button, pressed = self.CLICK_BUTTONS[msg]
                self.on_click(data.pt.x, data.pt.y, button, pressed, injected)
            elif msg in self.X_BUTTONS:
                button, pressed = self.X_BUTTONS[msg][data.mouseData >> 16]
                self.on_click(data.pt.x, data.pt.y, button, pressed, injected)
            elif msg in self.SCROLL_BUTTONS:
                mx, my = self.SCROLL_BUTTONS[msg]
                # 浮点除法：保留高精度触摸板的部分增量（如 0.5 格）
                dd = wintypes.SHORT(data.mouseData >> 16).value / WHEEL_DELTA
                self.on_scroll(data.pt.x, data.pt.y, dd * mx, dd * my, injected)
else:
    PrecisionMouseListener = mouse.Listener

# 默认热键配置
HOTKEY_TOGGLE_RECORD = "f9"       # 开始/停止录制
HOTKEY_TOGGLE_PLAY = "f10"        # 开始/停止回放
HOTKEY_TOGGLE_PAUSE = "f8"        # 暂停/继续（录制或回放）
HOTKEY_INSERT_RECORD = "f7"       # 回放暂停期间：录制一段新操作插入到暂停位置
HOTKEY_EMERGENCY_STOP = "f12"     # 紧急停止一切


class Recorder:
    """鼠标键盘事件录制器。"""

    def __init__(
        self,
        on_event: Optional[Callable[[RecordedEvent], None]] = None,
        on_hotkey: Optional[Callable[[str], None]] = None,
        record_mouse_move: bool = True,
        hotkeys: Optional[dict] = None,
    ):
        """
        on_event: 录制到一条事件时回调（监听线程中调用）
        on_hotkey: 检测到热键时回调，参数为热键名（监听线程中调用）
        record_mouse_move: 是否录制鼠标移动轨迹
        hotkeys: {热键名: key名字符串} 配置
        """
        self._on_event = on_event
        self._on_hotkey = on_hotkey
        self._record_mouse_move = record_mouse_move

        self._hotkeys = hotkeys or {
            "toggle_record": HOTKEY_TOGGLE_RECORD,
            "toggle_play": HOTKEY_TOGGLE_PLAY,
            "toggle_pause": HOTKEY_TOGGLE_PAUSE,
            "insert_record": HOTKEY_INSERT_RECORD,
            "emergency_stop": HOTKEY_EMERGENCY_STOP,
        }
        # 反查表：key 名 -> 热键名
        self._hotkey_lookup = {v: k for k, v in self._hotkeys.items()}

        self._recording = False
        self._start_time = 0.0
        self._events: list[RecordedEvent] = []
        self._lock = threading.Lock()

        # 暂停状态：暂停期间不记录事件，且暂停时长不计入时间戳
        self._paused = False
        self._pause_start = 0.0
        self._paused_total = 0.0

        # 防止热键自动重复（按住不放时只触发一次）
        self._hotkey_keys_down: set[str] = set()

        # 录制期间当前按住的修饰键（写入鼠标事件的 mods 元数据）
        self._held_modifiers: set[str] = set()

        self._kb_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None

    # ---------- 状态 ----------

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def events(self) -> list[RecordedEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    # ---------- 生命周期 ----------

    def start_listening(self) -> None:
        """启动常驻键盘监听（应用启动时调用一次）。"""
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.daemon = True
        self._kb_listener.start()

    def stop_listening(self) -> None:
        if self._kb_listener:
            self._kb_listener.stop()
            self._kb_listener = None

    def start_recording(self) -> bool:
        """开始录制。返回是否成功启动。"""
        if self._recording:
            return False
        self._recording = True
        self._start_time = time.monotonic()
        self._paused = False
        self._pause_start = 0.0
        self._paused_total = 0.0
        self._held_modifiers.clear()
        with self._lock:
            self._events.clear()
        # 启动鼠标监听（高精度子类：滚轮增量浮点化）
        self._mouse_listener = PrecisionMouseListener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self._mouse_listener.daemon = True
        self._mouse_listener.start()
        return True

    def stop_recording(self) -> list[RecordedEvent]:
        """停止录制并返回事件列表。"""
        if not self._recording:
            return []
        self._recording = False
        self._paused = False
        self._paused_total = 0.0
        self._held_modifiers.clear()
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        with self._lock:
            return list(self._events)

    # ---------- 暂停 ----------

    def pause_recording(self) -> bool:
        """暂停录制：暂停期间的事件不记录，时长不计入时间戳。"""
        if not self._recording or self._paused:
            return False
        self._paused = True
        self._pause_start = time.monotonic()
        return True

    def resume_recording(self) -> bool:
        """继续录制：把暂停时长计入 _paused_total，后续时间戳自动剔除。"""
        if not self._recording or not self._paused:
            return False
        self._paused_total += time.monotonic() - self._pause_start
        self._paused = False
        return True

    def toggle_pause(self) -> bool:
        """切换暂停状态。返回当前是否处于暂停中。"""
        if self._paused:
            self.resume_recording()
            return False
        self.pause_recording()
        return self._paused

    # ---------- 内部：事件记录 ----------

    def _now(self) -> float:
        """当前录制时间（秒），剔除累计暂停时长。暂停时冻结在暂停时刻。"""
        now = self._pause_start if self._paused else time.monotonic()
        return now - self._start_time - self._paused_total

    def _emit(self, event: RecordedEvent) -> None:
        with self._lock:
            self._events.append(event)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    def _try_hotkey(self, key) -> bool:
        """判断按键是否为热键；是则触发回调并返回 True。

        只在 key press 时调用；自动重复（按住不放）会被忽略。
        """
        name = key.name if isinstance(key, keyboard.Key) else None
        if name and name in self._hotkey_lookup:
            # 防自动重复：如果该热键已处于按下状态，跳过
            if name in self._hotkey_keys_down:
                return True  # 仍然吞掉该事件（不录制）
            self._hotkey_keys_down.add(name)
            hk_name = self._hotkey_lookup[name]
            if self._on_hotkey:
                try:
                    self._on_hotkey(hk_name)
                except Exception:
                    pass
            return True
        return False

    # 键盘回调（常驻监听线程）
    def _on_key_press(self, key):
        # 热键优先处理，且不录制
        if self._try_hotkey(key):
            return
        if not self._recording or self._paused:
            return
        # 跟踪修饰键按住状态（用于鼠标事件的 mods 元数据）
        name = key.name if isinstance(key, keyboard.Key) else None
        if name in MODIFIER_KEY_NAMES:
            self._held_modifiers.add(name)
        self._emit(RecordedEvent(self._now(), EV_KEY_PRESS, self._key_data(key)))

    def _on_key_release(self, key):
        # 热键释放：只清除按下标记，不再触发回调（避免按一下触发两次）
        name = key.name if isinstance(key, keyboard.Key) else None
        if name and name in self._hotkey_lookup:
            self._hotkey_keys_down.discard(name)
            return
        if not self._recording or self._paused:
            return
        if name in MODIFIER_KEY_NAMES:
            self._held_modifiers.discard(name)
        self._emit(RecordedEvent(self._now(), EV_KEY_RELEASE, self._key_data(key)))

    def _key_data(self, key) -> dict:
        """构建键盘事件的 data 字典，同时保存 key 字符串和 vk 虚拟键码。"""
        data = {"key": key_to_str(key)}
        # KeyCode 事件额外保存 vk（回放时优先用 vk，确保组合键正确）
        if isinstance(key, keyboard.KeyCode) and key.vk is not None:
            data["vk"] = key.vk
        return data

    def _mouse_data(self, base: dict) -> dict:
        """给鼠标事件附带当前修饰键状态（回放端据此确保组合键生效）。"""
        if self._held_modifiers:
            base["mods"] = sorted(self._held_modifiers)
        return base

    # 鼠标回调（录制期间监听线程）
    def _on_mouse_move(self, x, y):
        if not self._recording or self._paused or not self._record_mouse_move:
            return
        self._emit(RecordedEvent(self._now(), EV_MOUSE_MOVE, {"x": x, "y": y}))

    def _on_mouse_click(self, x, y, button, pressed):
        if not self._recording or self._paused:
            return
        btn = button.name if hasattr(button, "name") else str(button)
        self._emit(RecordedEvent(
            self._now(), EV_MOUSE_CLICK,
            self._mouse_data({"x": x, "y": y, "button": btn, "pressed": bool(pressed)}),
        ))

    def _on_mouse_scroll(self, x, y, dx, dy):
        if not self._recording or self._paused:
            return
        # pynput 对高精度触摸板的部分增量用整除计算（delta//120），
        # 不足一格时会得到 dy=0 的无意义事件，直接丢弃
        if dx == 0 and dy == 0:
            return
        self._emit(RecordedEvent(
            self._now(), EV_MOUSE_SCROLL,
            self._mouse_data({"x": x, "y": y, "dx": dx, "dy": dy}),
        ))
