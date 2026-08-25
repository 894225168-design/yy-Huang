# Mouse & Keyboard Recorder

Windows 桌面端的鼠标键盘操作录制与回放工具。录制鼠标点击/移动/滚轮、键盘按键（含组合键），以 JSON 脚本形式持久化，支持调速回放、循环执行、暂停/继续、全局热键控制。

## 功能特性

### 录制
- 全类型鼠标事件：点击、移动、滚轮
- 全类型键盘事件：单键、功能键、组合键（Ctrl+C / Shift+滚轮 等）
- 高精度滚轮增量：浮点化处理，支持高精度触摸板的部分增量
- DPI 感知：高分屏缩放下坐标一致
- 暂停录制：暂停期间不计入时间戳，回放无空白
- 修饰键元数据：鼠标事件附带当前修饰键状态，回放时双保险

### 回放
- 调速回放：0.5x ~ 4x
- 循环执行：1 ~ 999 次
- 暂停/继续：冻结线程，恢复后无缝衔接
- 修饰键时序保护：修饰键与鼠标事件间保证最小间隔，修复 Shift+滚轮偶发失效
- 系统定时器精度提升：回放期间提升至 1ms 分辨率
- 光标稳定延时：滚轮/点击前确保光标定位完成

### 界面
- 现代扁平化 UI（PyQt5）
- 左侧脚本管理（新建/重命名/删除）
- 右侧事件时间线表格（类型着色、实时刷新）
- 底部控制面板（录制/暂停/回放/紧急停止 + 速度/循环/轨迹选项）
- 状态栏圆点指示（就绪/录制/回放/暂停）

### 全局热键
| 热键 | 功能 |
|------|------|
| F9 | 开始/停止录制 |
| F10 | 开始/停止回放 |
| F8 | 暂停/继续（录制或回放） |
| F12 | 紧急停止一切 |

## 快速开始

### 环境要求
- Windows 10 / 11
- Python 3.10+

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-username/mouse-keyboard-recorder.git
cd mouse-keyboard-recorder

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# PowerShell
.venv\Scripts\Activate.ps1
# CMD
.venv\Scripts\activate.bat

# 安装依赖
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

或双击 `start.bat`。

## 使用说明

1. **录制操作**：按 F9 开始录制，执行你想要录制的鼠标键盘操作，再按 F9 停止。录制期间按 F8 可暂停/继续。
2. **管理脚本**：左侧脚本列表自动保存录制结果。可新建、重命名、删除脚本。
3. **回放操作**：选中一个脚本，设置回放速度和循环次数，按 F10 开始回放。回放期间按 F8 暂停/继续，按 F10 或 F12 停止。
4. **导出**：可将脚本导出为独立 JSON 文件。

## 项目结构

```
mouse_keyboard_recorder/
├── main.py              # 程序入口
├── main_window.py       # GUI 主窗口
├── recorder.py          # 录制模块（pynput 事件捕获）
├── player.py            # 回放模块（操作复刻）
├── event_types.py       # 事件数据模型
├── storage.py           # 脚本 JSON 持久化
├── requirements.txt     # Python 依赖
├── start.bat            # Windows 启动脚本
└── scripts/             # 录制脚本存储（运行时自动创建）
```

## 技术栈

- **Python 3.10+**
- **PyQt5** — GUI 框架
- **pynput** — 全局鼠标/键盘事件监听与控制
- **ctypes** — Windows API 调用（DPI 感知、定时器精度、滚轮精度子类化）

## 技术亮点

### 修饰键时序竞争修复
应用处理 WM_MOUSEWHEEL 时用 `GetAsyncKeyState` 读取修饰键实时状态，而非事件消息中的 wParam 快照。如果 Shift 释放事件与滚轮事件间隔太短，应用读到 Shift 已释放，导致 Shift+滚轮（水平滚动）退化为垂直滚动。回放端在修饰键与鼠标事件间插入 30ms 最小间隔保护。

### 高精度滚轮增量
pynput 原版用 `delta // 120` 整除计算格数，高精度触摸板的部分增量（如 60，即半格）被截断为 0。通过子类化 pynput 的 Win32 监听器，改为浮点除法 `delta / WHEEL_DELTA`，保留部分增量。

### 虚拟键码重建组合键
Ctrl 等修饰键按下时，pynput 将字符键的 `char` 报告为控制字符（如 Ctrl+C → `'\x03'`），无法用 `VkKeyScanW` 映射回 C 键。录制端检测控制字符时改存 `vk:{虚拟键码}`，回放端优先用 `from_vk` 重建按键。

## License

MIT License — 详见 [LICENSE](LICENSE) 文件。

## 贡献

欢迎提交 Issue 和 Pull Request。
