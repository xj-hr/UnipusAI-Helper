# -*- coding: utf-8 -*-
"""特殊题预处理阶段（D-03 抽离）的离线测试。

被测算子：`AISolver._handle_special_questions()` —— 从 `_process_current_tab_content`
中抽出的「闪卡 / 视频 / 音频 / 自检 / 讨论区」分发逻辑，返回
`("stop"|"done"|"continue", payload)`，由调用方决定外层返回值。

运行：
    python tests/test_special_questions.py

只 import `UnipusAI_Helper`（会拉起 selenium 等依赖），不需要浏览器与网络。
"""
import os
import sys
import traceback
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import UnipusAI_Helper as m  # noqa: E402

T = m.QuestionType


def make_solver(handlers, ai_available=True, stopping=False):
    """构造一个只具备该算子所需属性的假 solver。"""
    return SimpleNamespace(
        content_handlers=handlers,
        processed_hashes=set(),
        _last_tab_outcome="",
        _should_stop=lambda: stopping,
        _ai_available=lambda: ai_available,
    )


def make_handler(kinds, result=True, on_handle=None):
    """按题型命中的假 handler。"""
    class Handler:
        def can_handle(self, q):
            return q.q_type in kinds

        def handle(self, q):
            if on_handle:
                on_handle(q)
            return result

    return Handler()


def question(q_type):
    return SimpleNamespace(q_type=q_type)


def test_no_handler_continues():
    solver = make_solver([make_handler({T.AUDIO})])
    action, payload = m.AISolver._handle_special_questions(
        solver, [question(T.SINGLE_CHOICE)], "hash-x")
    assert action == "continue", action
    assert payload == (False, False), payload
    assert solver.processed_hashes == set()


def test_audio_marks_handled_and_continues():
    calls = []
    solver = make_solver([make_handler({T.AUDIO}, on_handle=lambda q: calls.append(q))])
    action, payload = m.AISolver._handle_special_questions(solver, [question(T.AUDIO)], "h")
    assert action == "continue", action
    assert payload == (True, False), payload
    assert len(calls) == 1
    assert "h" not in solver.processed_hashes, "音频页仍要走后续流程，不应提前登记 hash"


def test_video_finishes_page():
    solver = make_solver([make_handler({T.VIDEO})])
    action, payload = m.AISolver._handle_special_questions(solver, [question(T.VIDEO)], "h")
    assert action == "done", action
    assert payload is None
    assert "h" in solver.processed_hashes


def test_self_check_flag():
    solver = make_solver([make_handler({T.SELF_CHECK})])
    action, payload = m.AISolver._handle_special_questions(solver, [question(T.SELF_CHECK)], "h")
    assert action == "continue", action
    assert payload == (True, True), payload


def test_handler_failure_stops():
    solver = make_solver([make_handler({T.VIDEO}, result=False)])
    action, _ = m.AISolver._handle_special_questions(solver, [question(T.VIDEO)], "h")
    assert action == "stop", action
    assert "h" not in solver.processed_hashes, "处理失败不应登记 hash"


def test_discussion_without_ai_skips():
    solver = make_solver([make_handler({T.DISCUSSION_BOARD})], ai_available=False)
    action, _ = m.AISolver._handle_special_questions(solver, [question(T.DISCUSSION_BOARD)], "h")
    assert action == "stop", action
    assert solver._last_tab_outcome == "skipped_no_ai"


def test_stop_signal_short_circuits():
    solver = make_solver([make_handler({T.VIDEO})], stopping=True)
    action, _ = m.AISolver._handle_special_questions(solver, [question(T.VIDEO)], "h")
    assert action == "stop", action
    assert "h" not in solver.processed_hashes


TESTS = [
    ("无处理器 → 继续作答", test_no_handler_continues),
    ("音频 → 标记已处理但继续", test_audio_marks_handled_and_continues),
    ("视频 → 本页完成并登记", test_video_finishes_page),
    ("自检 → 标记 self_check", test_self_check_flag),
    ("处理器失败 → 停止", test_handler_failure_stops),
    ("讨论区无 AI → 跳过并记录原因", test_discussion_without_ai_skips),
    ("停止信号 → 立即停止", test_stop_signal_short_circuits),
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
