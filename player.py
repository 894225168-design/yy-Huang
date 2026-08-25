"""回放模块：复刻录制的鼠标键盘操作。

设计要点：
- 在独立线程中执行，按事件间的时间差（÷速度倍率）逐条还原。
- 支持随时停止：等待期分段睡眠，每段检查停止标志。
- 鼠标点击会先移动到录制时的坐标再按下，保证位置一致。
- 修饰键时序保护：Shift/Ctrl/Alt 与鼠标事件（滚轮/点击）之间保证最小间隔，
  防止应用用 GetAsyncKeyState 读实时修饰键状态时读到错误值（Shift+滚轮偶发失效的根因）。
- 回放期间把系统定时器分辨率提升到 1ms，改善短间隔事件的节奏准确性。
"""

import ctypes
import threading
import time
from typing import Callable, Optional

from pynput import keyboard, mouse

from event_types import (
    EV_KEY_PRESS, EV_KEY_RELEASE, EV_MOUSE_CLICK, EV_MOUSE_MOVE, EV_MOUSE_SCROLL,
    MODIFIER_KEY_NAMES, RecordedEvent, str_to_key,
)

# 分段睡眠的步长（秒），保证停止指令的响应速度
_SLEEP_STEP = 0.01

# 修饰键保护：修饰键按下/释放与相邻鼠标事件之间的最小间隔（秒）。
# 许多应用处理 WM_MOUSEWHEEL 时用 GetAsyncKeyState 读修饰键实时状态，
# 间隔太短会导致应用处理消息时修饰键已被释放，组合操作（如 Shift+滚轮）失效。
_MODIFIER_GUARD = 0.03

# 鼠标事件注入前的光标稳定延时（秒）：确保滚轮消息路由到正确窗口
_MOUSE_SETTLE = 0.01

# 兼容别名（引用 event_types 中的共享常量）
_MODIFIER_KEY_NAMES = MODIFIER_KEY_NAMES


class Player:
    """操作回放器。"""

    def __init__(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_finished: Optional[Callable[[bool], None]] = None,
    ):
        """
        on_progress(已回放条数, 总条数): 每回放一条回调一次（回放线程中）
        on_finished(was_stopped: bool): 回放结束回调（回放线程中）
        """
        self._on_progress = on_progress
        self._on_finished = on_finished

        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        # 暂停事件：set=运行中，clear=暂停中（回放线程在 clear 时阻塞等待）
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._playing = False
        self._lock = threading.Lock()

        self._mouse_ctrl = mouse.Controller()
        self._kb_ctrl = keyboard.Controller()

        # 修饰键时序保护状态（回放线程内使用）
        self._held_modifiers: set = set()      # 当前按住的修饰键
        self._last_modifier_press = 0.0        # 最近一次修饰键按下时刻
        self._last_mouse_dispatch = 0.0        # 最近一次鼠标事件（滚轮/点击）分发时刻

    # ---------- 状态 ----------

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def paused(self) -> bool:
        return self._playing and not self._pause_event.is_set()

    # ---------- 控制 ----------

    def play(
        self,
        events: list[RecordedEvent],
        speed: float = 1.0,
        loops: int = 1,
    ) -> bool:
        """开始回放。返回是否成功启动。

        events: 事件列表（按时间排序）
        speed: 速度倍率，1.0 为原速，2.0 为两倍速
        loops: 循环次数，1 为单次
        """
        with self._lock:
            if self._playing:
                return False
            if not events:
                return False
            speed = max(0.1, float(speed))
            loops = max(1, int(loops))
            self._stop_flag.clear()
            self._pause_event.set()
            self._held_modifiers.clear()
            self._last_modifier_press = 0.0
            self._last_mouse_dispatch = 0.0
            self._playing = True

        self._thread = threading.Thread(
            target=self._run, args=(list(events), speed, loops), daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """请求停止回放（异步，立即返回）。"""
        self._stop_flag.set()
        # 解除暂停阻塞，保证暂停状态下也能立即停止
        self._pause_event.set()

    def pause(self) -> bool:
        """暂停回放（冻结在当前位置）。返回是否成功。"""
        if not self._playing or not self._pause_event.is_set():
            return False
        self._pause_event.clear()
        return True

    def resume(self) -> bool:
        """继续回放。返回是否成功。"""
        if not self._playing or self._pause_event.is_set():
            return False
        self._pause_event.set()
        return True

    def toggle_pause(self) -> bool:
        """切换暂停状态。返回切换后是否处于暂停中。"""
        if self.paused:
            self.resume()
            return False
        self.pause()
        return self.paused

    def _run(self, events: list[RecordedEvent], speed: float, loops: int) -> None:
        was_stopped = False
        total = len(events) * loops
        done = 0
        self._set_timer_resolution(True)
        try:
            for loop_i in range(loops):
                prev_t = 0.0
                for ev in events:
                    # 暂停时阻塞在此，直到继续（或停止）
                    self._pause_event.wait()
                    if self._stop_flag.is_set():
                        was_stopped = True
                        raise StopIteration
                    # 等待到该事件应发生的时刻
                    delay = (ev.timestamp - prev_t) / speed
                    prev_t = ev.timestamp
                    if delay > 0 and not self._sleep(delay):
                        was_stopped = True
                        raise StopIteration
                    self._dispatch(ev)
                    done += 1
                    if self._on_progress:
                        try:
                            self._on_progress(done, total)
                        except Exception:
                            pass
                    if self._stop_flag.is_set():
                        was_stopped = True
                        raise StopIteration
        except StopIteration:
            pass
        finally:
            self._set_timer_resolution(False)
            with self._lock:
                self._playing = False
            if self._on_finished:
                try:
                    self._on_finished(was_stopped)
                except Exception:
                    pass

    @staticmethod
    def _set_timer_resolution(high: bool) -> None:
        """回放期间把系统定时器分辨率提升到 1ms（Windows 默认 15.6ms）。

        短间隔事件的节奏依赖 time.sleep 的粒度，1ms 分辨率能显著改善
        Shift+滚轮 等密集操作的时序还原度。
        """
        try:
            if high:
                ctypes.windll.winmm.timeBeginPeriod(1)
            else:
                ctypes.windll.winmm.timeEndPeriod(1)
        except Exception:
            pass

    # ---------- 内部 ----------

    def _sleep(self, seconds: float) -> bool:
        """分段睡眠，随时可被打断或暂停。返回 False 表示收到停止指令。"""
        deadline = time.monotonic() + seconds
        while True:
            if self._stop_flag.is_set():
                return False
            if not self._pause_event.is_set():
                # 暂停中：阻塞等待恢复，恢复后把暂停时长补回截止时间
                pause_begin = time.monotonic()
                self._pause_event.wait()
                deadline += time.monotonic() - pause_begin
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(_SLEEP_STEP, remaining))

    def _dispatch(self, ev: RecordedEvent) -> None:
        et, d = ev.event_type, ev.data
        try:
            if et == EV_MOUSE_MOVE:
                self._mouse_ctrl.position = (d["x"], d["y"])
            elif et == EV_MOUSE_CLICK:
                self._ensure_modifiers(d.get("mods"))
                self._guard_before_mouse()
                self._mouse_ctrl.position = (d["x"], d["y"])
                time.sleep(_MOUSE_SETTLE)
                # Button 枚举按名称查找（Button["left"]），不是按值（Button("left")会报错）
                btn_name = d.get("button", "left")
                btn = mouse.Button[btn_name]
                if d.get("pressed"):
                    self._mouse_ctrl.press(btn)
                else:
                    self._mouse_ctrl.release(btn)
                self._last_mouse_dispatch = time.monotonic()
            elif et == EV_MOUSE_SCROLL:
                self._ensure_modifiers(d.get("mods"))
                self._guard_before_mouse()
                self._mouse_ctrl.position = (d["x"], d["y"])
                time.sleep(_MOUSE_SETTLE)
                self._mouse_ctrl.scroll(d.get("dx", 0), d.get("dy", 0))
                self._last_mouse_dispatch = time.monotonic()
            elif et == EV_KEY_PRESS:
                key_name = d.get("key", "")
                self._kb_ctrl.press(self._resolve_key(d))
                if key_name in _MODIFIER_KEY_NAMES:
                    self._held_modifiers.add(key_name)
                    self._last_modifier_press = time.monotonic()
            elif et == EV_KEY_RELEASE:
                key_name = d.get("key", "")
                if key_name in _MODIFIER_KEY_NAMES:
                    self._guard_before_modifier_release()
                self._kb_ctrl.release(self._resolve_key(d))
                self._held_modifiers.discard(key_name)
        except Exception:
            # 单条事件失败不影响整体回放
            pass

    def _ensure_modifiers(self, mods) -> None:
        """鼠标事件注入前，确保录制时按住的修饰键处于按下状态。

        录制端在鼠标事件中附带了 mods 元数据；即使事件流时序被干扰
        （或修饰键按下事件异常丢失），这里也能兜底按下，双保险。
        释放仍由录制的 key_release 事件负责，不在此处理。
        """
        if not mods:
            return
        for name in mods:
            if name not in self._held_modifiers:
                try:
                    self._kb_ctrl.press(str_to_key(name))
                    self._held_modifiers.add(name)
                    self._last_modifier_press = time.monotonic()
                except Exception:
                    pass

    def _guard_before_mouse(self) -> None:
        """鼠标事件（滚轮/点击）注入前的修饰键保护。

        如果修饰键刚按下不久，补足最小间隔，确保应用在处理鼠标消息前
        已经能感知到修饰键处于按下状态。
        """
        if not self._held_modifiers:
            return
        elapsed = time.monotonic() - self._last_modifier_press
        if elapsed < _MODIFIER_GUARD:
            time.sleep(_MODIFIER_GUARD - elapsed)

    def _guard_before_modifier_release(self) -> None:
        """修饰键释放前的保护。

        如果刚分发过鼠标事件，补足最小间隔，确保应用处理该鼠标消息时
        修饰键仍处于按下状态（修复 Shift+滚轮偶发变纵向滚动的问题）。
        """
        if not self._held_modifiers or self._last_mouse_dispatch == 0.0:
            return
        elapsed = time.monotonic() - self._last_mouse_dispatch
        if elapsed < _MODIFIER_GUARD:
            time.sleep(_MODIFIER_GUARD - elapsed)

    def _resolve_key(self, d: dict):
        """从事件数据重建按键对象。优先用 vk（虚拟键码，不受修饰键影响）。"""
        if "vk" in d:
            return keyboard.KeyCode.from_vk(d["vk"])
        return str_to_key(d["key"])
