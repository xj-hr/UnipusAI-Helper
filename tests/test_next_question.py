# -*- coding: utf-8 -*-
"""翻页阶段（D-03 抽离）的离线测试。

被测算子：`AISolver._advance_to_next_question()` —— 从 `_process_current_tab_content`
抽出的「点击下一题 + 等待内容变化 + 页数上限」逻辑。

运行：
    python tests/test_next_question.py
"""
import os
import sys
import traceback
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import UnipusAI_Helper as m  # noqa: E402


def make_solver(wait_ok=True, stopping=False):
    return SimpleNamespace(
        driver=object(),
        _should_stop=lambda: stopping,
        _wait_for_content_change=lambda signature, timeout=30: wait_ok,
    )


def call(solver, next_btn, signature="sig", page_num=1, click_ok=True):
    """临时替换 WebDriverHelper.safe_click，调用算子后恢复。"""
    original = m.WebDriverHelper.safe_click
    m.WebDriverHelper.safe_click = staticmethod(lambda driver, element: click_ok)
    try:
        return m.AISolver._advance_to_next_question(solver, next_btn, signature, page_num)
    finally:
        m.WebDriverHelper.safe_click = original


def test_no_next_button():
    solver = make_solver()
    assert call(solver, None) == ("none", None)


def test_click_failure_stops():
    solver = make_solver()
    assert call(solver, object(), click_ok=False) == ("stop", None)


def test_content_unchanged_stops():
    solver = make_solver(wait_ok=False)
    assert call(solver, object()) == ("stop", None)


def test_success_returns_incremented_page():
    solver = make_solver()
    action, page = call(solver, object(), page_num=5)
    assert action == "next" and page == 6, (action, page)


def test_page_limit_50():
    solver = make_solver()
    assert call(solver, object(), page_num=50) == ("stop", None), "第 51 页应触发上限保护"
    action, page = call(solver, object(), page_num=49)
    assert action == "next" and page == 50


def test_stop_before_click():
    solver = make_solver(stopping=True)
    assert call(solver, object()) == ("stop", None)


TESTS = [
    ("无下一题按钮 → none", test_no_next_button),
    ("点击失败 → 停止", test_click_failure_stops),
    ("内容未变化 → 停止", test_content_unchanged_stops),
    ("翻页成功 → 页码 +1", test_success_returns_incremented_page),
    ("第 51 页触发上限", test_page_limit_50),
    ("已请求停止 → 不点击", test_stop_before_click),
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
