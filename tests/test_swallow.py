# -*- coding: utf-8 -*-
"""静默异常留痕与热点升级的离线测试（缺陷台账 D-01）。

运行方式：
    python tests/test_swallow.py

覆盖：
  - 阈值前只 DEBUG，阈值当次返回 True 并推送一条告警
  - 同一位置只告警一次，计数继续累计
  - hotspots() 按次数排序、支持最小次数过滤
  - reset_counts() 清空计数与告警
  - 不在 except 块内调用时也能安全记录（exc_type 记为 None）

只 import `unipus_helper.swallow`，不需要 Qt / 浏览器 / 网络。
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unipus_helper import swallow  # noqa: E402


def _swallow(context, times=1):
    """在真实 except 块内调用，模拟业务代码的吞异常场景。"""
    results = []
    for i in range(times):
        try:
            raise ValueError(f"boom-{i}")
        except Exception:
            results.append(swallow.log_swallowed(context))
    return results


def test_threshold_once():
    swallow.reset_counts()
    results = _swallow("demo:1", 19)
    assert results == [False] * 19, results
    assert swallow.pending_alert_count() == 0
    assert swallow.log_swallowed.__name__ == "log_swallowed"

    last = _swallow("demo:1", 1)[0]
    assert last is True, "跨过阈值时应返回 True"
    assert swallow.pending_alert_count() == 1

    alerts = swallow.drain_alerts()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.context == "demo:1"
    assert alert.count == 20
    assert alert.exc_type == "ValueError"
    assert "boom-" in alert.message
    assert swallow.pending_alert_count() == 0, "drain 后队列应清空"


def test_no_duplicate_alert():
    swallow.reset_counts()
    _swallow("dup:9", 20)
    assert swallow.pending_alert_count() == 1
    assert len(swallow.drain_alerts()) == 1
    _swallow("dup:9", 5)
    assert swallow.pending_alert_count() == 0, "同一位置不应重复推送告警"
    assert swallow.swallowed_counts()["dup:9"] == 25


def test_hotspots_sorted():
    swallow.reset_counts()
    _swallow("hot:a", 25)
    _swallow("warm:b", 5)
    rows = swallow.hotspots(min_count=1)
    assert [r["context"] for r in rows] == ["hot:a", "warm:b"], rows
    assert rows[0]["count"] == 25
    assert [r["context"] for r in swallow.hotspots()] == ["hot:a"], "默认只返回达到阈值的位置"


def test_reset():
    swallow.reset_counts()
    _swallow("reset:1", 20)
    assert swallow.pending_alert_count() == 1
    swallow.reset_counts()
    assert swallow.swallowed_counts() == {}
    assert swallow.pending_alert_count() == 0
    assert swallow.hotspots(min_count=1) == []


def test_outside_except():
    swallow.reset_counts()
    assert swallow.log_swallowed("plain:1") is False
    assert swallow.swallowed_counts()["plain:1"] == 1
    assert swallow.pending_alert_count() == 0


def test_custom_threshold():
    swallow.reset_counts()
    results = []
    for _ in range(3):
        try:
            raise RuntimeError("x")
        except Exception:
            results.append(swallow.log_swallowed("custom:1", warn_every=3))
    assert results == [False, False, True], results
    assert swallow.drain_alerts()[0].exc_type == "RuntimeError"


TESTS = [
    ("阈值前静默、阈值当次告警", test_threshold_once),
    ("同一位置不重复告警", test_no_duplicate_alert),
    ("热点按次数排序", test_hotspots_sorted),
    ("reset 清空计数与告警", test_reset),
    ("except 外调用安全", test_outside_except),
    ("自定义阈值生效", test_custom_threshold),
]


def main():
    failed = 0
    for name, test in TESTS:
        try:
            test()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
