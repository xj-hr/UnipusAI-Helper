# -*- coding: utf-8 -*-
"""录音题作答阶段的行为基线（D-03 拆分前置）。

被测对象：`AISolver._process_current_tab_content()` 中「录音题逐条作答」那段
（约 53 行：TTS 判定 → 主观题写稿 → executor.execute → 完成率不足即中止）。

做法：用 `object.__new__(AISolver)` 造一个不跑构造函数的假 solver，只挂该段需要的
属性与方法；`driver` 为占位对象，模块级的浮层关闭/提交钩子打桩。**不需要浏览器与网络。**

这批用例是拆分前写好的「行为快照」：抽成独立方法后必须仍然全绿。

运行：
    python tests/test_record_answering.py
"""
import os
import sys
import traceback
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import UnipusAI_Helper as m  # noqa: E402

T = m.QuestionType


class FakeExecutor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.submit_count = 0

    def execute(self, question, script=""):
        self.calls.append({"type": question.q_type, "script": script})
        return self.results.pop(0) if self.results else True

    def submit(self):
        self.submit_count += 1
        return True


def record_question(script_needed=False, kind="RECORD"):
    return SimpleNamespace(q_type=getattr(T, kind),
                           is_self_submitting_record=False,
                           needs_speech_script=script_needed)


def build_solver(questions, exec_results, tts_enabled=True, ai_available=True):
    solver = object.__new__(m.AISolver)
    solver.driver = SimpleNamespace()
    solver.executor = FakeExecutor(exec_results)
    solver.parser = SimpleNamespace(incomplete=False, parse_all=lambda: (questions, ""))
    solver.content_handlers = []
    solver.processed_hashes = set()
    solver.answer_api = None
    solver.stop_requested = None
    solver._last_tab_outcome = ""

    solver._should_stop = lambda: False
    solver._generate_content_hash_from_direction = lambda: "dir-1"
    solver._is_publish_page = lambda: False
    solver._is_skipped_record_only_page = lambda: False
    solver._answer_api_report = lambda: None
    solver._harvest_vocabulary = lambda: None
    solver._generate_questions_signature = lambda qs: "sig-1"
    solver._skip_record_mode = lambda: "off"
    solver._vocab = lambda: []
    solver._needs_vocabulary = lambda qs: False
    solver._tts = lambda: SimpleNamespace(enabled=tts_enabled)
    solver._ai_available = lambda: ai_available
    solver._speaking_script_for = lambda q, d: "speech script"
    solver._find_next_question_button = lambda: None
    solver._wait_for_submit_complete = lambda: True
    solver._answer_api_page_answers = lambda qs: None
    solver._last_question_types = set()
    return solver


def run(solver, questions):
    """调用被测函数，同时把模块级 DOM 钩子打桩。"""
    original_dismiss = m._dismiss_known_info_overlays
    original_hook = m._install_submit_network_hook
    m._dismiss_known_info_overlays = lambda driver: None
    m._install_submit_network_hook = lambda driver: None
    try:
        return solver._process_current_tab_content("chapter", "tab", 0, 0)
    finally:
        m._dismiss_known_info_overlays = original_dismiss
        m._install_submit_network_hook = original_hook


def test_all_records_answered():
    solver = build_solver([record_question(), record_question()], [True, True])
    ok = run(solver, None)
    assert ok is True, f"全部作答成功应返回 True，实际 {ok}"
    assert len(solver.executor.calls) == 2, solver.executor.calls
    assert solver.executor.submit_count == 1, "本页有题目，应调用一次提交"
    assert solver._last_tab_outcome == "done", solver._last_tab_outcome


def test_partial_failure_stops_page():
    solver = build_solver([record_question(), record_question()], [True, False])
    ok = run(solver, None)
    assert ok is False, "有题未完成应返回 False"
    assert len(solver.executor.calls) == 2
    assert solver.executor.submit_count == 0, "未完成时不应提交"


def test_tts_disabled_skips_question():
    solver = build_solver([record_question(script_needed=True)], [True], tts_enabled=False)
    ok = run(solver, None)
    assert ok is False, "TTS 关闭导致题目被跳过，应判未完成"
    assert solver.executor.calls == [], "TTS 不可用时不应对该题执行录音"


def test_missing_ai_script_marks_skip_reason():
    solver = build_solver([record_question(script_needed=True)], [True], ai_available=False)
    ok = run(solver, None)
    assert ok is False
    assert solver._last_tab_outcome == "skipped_no_ai", solver._last_tab_outcome


def test_oral_aloud_uses_tts_without_script():
    solver = build_solver([record_question(script_needed=False, kind="ORAL_ALOUD")], [True])
    ok = run(solver, None)
    assert ok is True
    assert len(solver.executor.calls) == 1
    assert solver.executor.calls[0]["script"] == "", "跟读题不应生成脚本"


TESTS = [
    ("全部录音题作答成功 → 提交", test_all_records_answered),
    ("部分失败 → 不提交并中止", test_partial_failure_stops_page),
    ("TTS 关闭 → 跳过该题", test_tts_disabled_skips_question),
    ("缺 AI 写稿 → 标记 skipped_no_ai", test_missing_ai_script_marks_skip_reason),
    ("跟读题 → 不生成脚本", test_oral_aloud_uses_tts_without_script),
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
