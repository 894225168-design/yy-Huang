"""插入录制功能的无头测试：验证 Player.insert_at_pause 的拼接与时序。

不打真实输入：_dispatch 被替换为记录器，仅验证事件派发顺序、
插入位置、时间戳重映射和回放继续行为。
"""

import sys
import threading
import time

from event_types import RecordedEvent, EV_KEY_PRESS, EV_MOUSE_CLICK
from player import Player


def ev(t, mark):
    return RecordedEvent(t, EV_KEY_PRESS, {"key": mark})


def main():
    # 原始事件：0.2, 0.5, 1.2, 2.0（4 条）
    orig = [ev(0.2, "e0"), ev(0.5, "e1"), ev(1.2, "e2"), ev(2.0, "e3")]

    dispatched = []
    done_gate = threading.Event()

    def fake_dispatch(e):
        dispatched.append(e.data["key"])

    def on_progress(done, total):
        if done >= 2:
            done_gate.set()

    finished = {}

    def on_finished(stopped):
        finished["stopped"] = stopped
        finished["at"] = time.monotonic()

    p = Player(on_progress=on_progress, on_finished=on_finished)
    p._dispatch = fake_dispatch  # 打桩：不注入真实输入
    p._set_timer_resolution = lambda high: None  # 不动系统定时器

    ok = p.play(orig, speed=1.0, loops=1)
    assert ok, "play 启动失败"

    # 等到前两条派发完成（确定性暂停点：e2 之前）
    assert done_gate.wait(timeout=5), "等待进度超时"
    time.sleep(0.05)  # 让回放线程进入 e2 的等待期
    assert p.pause(), "暂停失败"
    time.sleep(0.1)

    # 暂停位置断言：next_index 应为 2（e2 未派发），prev_t 应为 0.5（e1 的时间戳）
    with p._lock:
        assert p._next_index == 2, f"next_index={p._next_index}，应为 2"
        assert abs(p._prev_t - 0.5) < 1e-9, f"prev_t={p._prev_t}，应为 0.5"

    # 插入段：相对时间 0.3、0.8（2 条，时长 0.8）
    seg = [ev(0.3, "ins0"), ev(0.8, "ins1")]
    merged = p.insert_at_pause(seg)
    assert merged is not None, "insert_at_pause 返回 None"
    assert len(merged) == 6, f"合并后应为 6 条，实际 {len(merged)}"

    # 合并列表的时间戳断言：
    # ins0 = 0.5+0.3 = 0.8；ins1 = 0.5+0.8 = 1.3
    # e2 = 1.2+0.8 = 2.0；e3 = 2.0+0.8 = 2.8
    ts = [round(e.timestamp, 6) for e in merged]
    expect_ts = [0.2, 0.5, 0.8, 1.3, 2.0, 2.8]
    assert ts == expect_ts, f"时间戳重映射错误：{ts} != {expect_ts}"
    # 原始脚本对象不应被修改
    assert [e.timestamp for e in orig] == [0.2, 0.5, 1.2, 2.0], "原始事件列表被污染"

    # 暂停状态下再次插入应失败（回放已在暂停中……实际上仍暂停，应允许；
    # 但未暂停时插入必须失败）—— 先恢复，验证运行中插入被拒绝
    assert p.resume(), "恢复失败"
    time.sleep(0.05)
    assert p.insert_at_pause([ev(0.1, "x")]) is None, "运行中插入应返回 None"
    assert p.pause(), "再次暂停失败"
    # 暂停中插入空列表返回 None
    assert p.insert_at_pause([]) is None, "空插入应返回 None"
    assert p.resume(), "再次恢复失败"

    # 等回放自然结束
    deadline = time.monotonic() + 15
    while "stopped" not in finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "stopped" in finished, "回放未结束（超时）"
    assert finished["stopped"] is False, "回放不应被视为手动停止"

    # 派发顺序断言：e0, e1 之后先执行插入段，再继续 e2, e3
    assert dispatched == ["e0", "e1", "ins0", "ins1", "e2", "e3"], \
        f"派发顺序错误：{dispatched}"

    print("ALL_TESTS_PASSED")


if __name__ == "__main__":
    sys.exit(main())
