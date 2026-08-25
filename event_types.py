"""事件数据模型：定义录制事件的结构、序列化与反序列化。"""

from dataclasses import dataclass, field
from typing import Optional

from pynput import keyboard


# ---------- 事件类型常量 ----------

EV_MOUSE_CLICK = "mouse_click"
EV_MOUSE_MOVE = "mouse_move"
EV_MOUSE_SCROLL = "mouse_scroll"
EV_KEY_PRESS = "key_press"
EV_KEY_RELEASE = "key_release"

MOUSE_BUTTONS = ("left", "right", "middle")

# 事件类型的中文标签（用于界面表格的类型列）
TYPE_LABELS = {
    EV_MOUSE_CLICK: "鼠标点击",
    EV_MOUSE_MOVE: "鼠标移动",
    EV_MOUSE_SCROLL: "鼠标滚轮",
    EV_KEY_PRESS: "按键按下",
    EV_KEY_RELEASE: "按键释放",
}

# 鼠标按键的中文名
BTN_NAMES = {"left": "左", "right": "右", "middle": "中"}

# 参与组合操作的修饰键名（录制/回放共用）
MODIFIER_KEY_NAMES = {
    "shift", "shift_l", "shift_r",
    "ctrl", "ctrl_l", "ctrl_r",
    "alt", "alt_l", "alt_r",
    "cmd", "cmd_l", "cmd_r",
}

# Key 枚举名到对象的映射（用于回放时重建按键）
_SPECIAL_KEYS = {k.name: k for k in keyboard.Key}


def key_to_str(key) -> str:
    """把 pynput 按键对象转换为可序列化字符串（用于显示和兜底回放）。

    - 特殊键（ctrl/enter/space...）: 直接用枚举名，如 "ctrl_l"
    - 可打印字符键: 用其字符，如 "a"、"1"
    - 控制字符（Ctrl+key 组合时 pynput 报告 \\x03 等）: 改用 vk 虚拟键码
    """
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode):
        if key.char is not None:
            # Ctrl 等修饰键按下时 char 变成控制字符（如 Ctrl+C -> '\x03'），
            # 用 char 回放无法正确还原组合键，改用 vk
            if 0 <= ord(key.char) < 32 or ord(key.char) == 127:
                if key.vk is not None:
                    return f"vk:{key.vk}"
            return key.char
        if key.vk is not None:
            return f"vk:{key.vk}"
    return str(key)


def str_to_key(s: str):
    """把字符串还原为 pynput 按键对象。"""
    if s in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[s]
    if s.startswith("vk:"):
        return keyboard.KeyCode.from_vk(int(s[3:]))
    return keyboard.KeyCode.from_char(s)


@dataclass
class RecordedEvent:
    """一条录制事件。

    timestamp: 相对录制开始的秒数
    event_type: EV_* 常量之一
    data: 类型相关的载荷字典
    """

    timestamp: float
    event_type: str
    data: dict = field(default_factory=dict)

    # ---------- 序列化 ----------

    def to_dict(self) -> dict:
        return {
            "t": round(self.timestamp, 4),
            "type": self.event_type,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RecordedEvent":
        return cls(timestamp=float(d["t"]), event_type=d["type"], data=dict(d.get("data", {})))

    # ---------- 展示 ----------

    def type_label(self) -> str:
        """事件类型的中文标签，用于界面表格的类型列。"""
        return TYPE_LABELS.get(self.event_type, self.event_type)

    def detail_text(self) -> str:
        """事件详情（不含时间和类型），用于界面表格的详情列。"""
        et = self.event_type
        d = self.data
        if et == EV_MOUSE_CLICK:
            action = "按下" if d.get("pressed") else "释放"
            btn = BTN_NAMES.get(d.get("button"), d.get("button", "?"))
            return f"{action}{btn}键 @ ({d.get('x')}, {d.get('y')})"
        if et == EV_MOUSE_MOVE:
            return f"({d.get('x')}, {d.get('y')})"
        if et == EV_MOUSE_SCROLL:
            direction = "上" if d.get("dy", 0) > 0 else "下"
            mods = d.get("mods")
            prefix = "+".join(mods) + "+" if mods else ""
            return f"{prefix}向{direction}滚 {abs(d.get('dy', 0)):g} 格 @ ({d.get('x')}, {d.get('y')})"
        if et in (EV_KEY_PRESS, EV_KEY_RELEASE):
            return self._key_display()
        return ""

    def describe(self) -> str:
        """生成人类可读的一行描述。"""
        t = f"{self.timestamp:7.2f}s"
        return f"[{t}] {self.type_label()} {self.detail_text()}"

    def _key_display(self) -> str:
        raw = self.data.get("key", "")
        if not raw:
            return "?"
        # vk 码显示为可读名称
        if raw.startswith("vk:"):
            _VK_NAMES = {
                8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift", 17: "Ctrl",
                18: "Alt", 20: "CapsLock", 27: "Esc", 32: "空格",
                33: "PgUp", 34: "PgDn", 35: "End", 36: "Home",
                37: "←", 38: "↑", 39: "→", 40: "↓", 45: "Insert", 46: "Delete",
                48: "0", 49: "1", 50: "2", 51: "3", 52: "4",
                53: "5", 54: "6", 55: "7", 56: "8", 57: "9",
                65: "A", 66: "B", 67: "C", 68: "D", 69: "E", 70: "F",
                71: "G", 72: "H", 73: "I", 74: "J", 75: "K", 76: "L",
                77: "M", 78: "N", 79: "O", 80: "P", 81: "Q", 82: "R",
                83: "S", 84: "T", 85: "U", 86: "V", 87: "W", 88: "X",
                89: "Y", 90: "Z",
                112: "F1", 113: "F2", 114: "F3", 115: "F4", 116: "F5",
                117: "F6", 118: "F7", 119: "F8", 120: "F9", 121: "F10",
                122: "F11", 123: "F12",
                186: ";", 187: "=", 188: ",", 189: "-", 190: ".",
                191: "/", 192: "`", 219: "[", 220: "\\", 221: "]", 222: "'",
            }
            try:
                vk = int(raw[3:])
                name = _VK_NAMES.get(vk)
                if name:
                    return f"VK({name})"
                return f"VK({vk})"
            except ValueError:
                return raw
        # 特殊键美化显示
        pretty = {
            "space": "空格", "enter": "回车", "backspace": "退格",
            "delete": "Delete", "escape": "Esc", "tab": "Tab",
            "caps_lock": "CapsLock", "shift_l": "左Shift", "shift_r": "右Shift",
            "ctrl_l": "左Ctrl", "ctrl_r": "右Ctrl", "alt_l": "左Alt", "alt_r": "右Alt",
            "cmd": "Win", "up": "↑", "down": "↓", "left": "←", "right": "→",
        }
        return pretty.get(raw, raw if len(raw) > 1 else raw.upper())
