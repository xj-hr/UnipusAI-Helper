# -*- coding: utf-8 -*-
"""普通题作答阶段的行为基线（D-03 最后一段，抽取前置）。

被测对象：`AISolver._process_current_tab_content()` 中「官方答案 / AI 作答」那段
（约 186 行）。三条主路径各一组用例：

  1. 官方答案命中 → 全部填写成功，跳过 AI
  2. 官方答案未命中 → 回落 AI，逐题填写
  3. AI 未返回答案 → 停止当前任务，返回 False

做法与录音段一致：`object.__new__(AISolver)` + 全量假对象，不启动浏览器。
这批用例是抽取 `_answer_normal_questions()` 前后的对照基线。

运行：
    python tests/test_normal_questions.py
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
        self._exact_official_mode = False

    def execute(self, question, answer=""):
        self.calls.append({"number": question.number, "answer": answer,
                           "official": self._exact_official_mode})
        return self.results.pop(0) if self.results else True

    def submit(self):
        self.submit_count += 1
        return True

    @staticmethod
    def _parse_sorting_order(answer, letters):
        return answer


class FakeAccuracy:
    def apply_to_items(self, items, enforce_submit_floor=False):
        return [answer for _, answer in items], None


class FakePromptBuilder:
    @staticmethod
    def build(questions, directions):
        return "prompt"


class FakeAiClient:
    def __init__(self, response):
        self.response = response
        self.asked = 0
        self.material_messages = []
        self.passages = []

    def add_passage_if_new(self, passage):
        self.passages.append(passage)

    def ask(self, prompt, stop_requested=None, screenshot=None, require_image=False):
        self.asked += 1
        return self.response


def single_choice(number):
    return SimpleNamespace(number=number, q_type=T.SINGLE_CHOICE, inputs=[], options=[],
                           is_self_submitting_record=False, needs_speech_script=False)


def build_solver(questions, exec_results, ai_response="", official_answers=None):
    solver = object.__new__(m.AISolver)
    solver.driver = SimpleNamespace(find_elements=lambda *a, **k: [],
                                    execute_script=lambda *a, **k: None)
    solver.executor = FakeExecutor(exec_results)
    solver.parser = SimpleNamespace(incomplete=False, parse_all=lambda: (questions, ""))
    solver.content_handlers = []
    solver.processed_hashes = set()
    solver.answer_api = None if official_answers is None else SimpleNamespace(
        enabled=True, abandoned=False, stats={},
        reset=lambda: None, mark_fallback=lambda: None, abandon=lambda *a: None,
        consume=lambda *a: None)
    solver.stop_requested = None
    solver._last_tab_outcome = ""
    solver._retry_hint = ""
    solver.ai_client = FakeAiClient(ai_response)
    solver.prompt_builder = FakePromptBuilder()

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
    solver._tts = lambda: SimpleNamespace(enabled=True)
    solver._ai_available = lambda: True
    solver._speaking_script_for = lambda q, d: ""
    solver._find_next_question_button = lambda: None
    solver._wait_for_submit_complete = lambda: True
    solver._answer_api_page_answers = lambda qs: official_answers
    solver._last_question_types = set()
    solver._accuracy_controller = lambda: FakeAccuracy()
    solver._ensure_reading_context_for_ai = lambda: False
    solver._has_video_on_page = lambda: False
    solver._has_audio_on_page = lambda: False
    solver._extract_passage = lambda: None
    solver._question_screenshot = lambda qs: None
    solver._requires_image_context = lambda qs: False
    solver._extract_single_answer = lambda response, number: response
    solver._reorder_sorting_by_transcript = lambda q, order: order
    solver._repair_questions = lambda failed, directions: 0
    return solver


def run(solver):
    original_dismiss = m._dismiss_known_info_overlays
    original_hook = m._install_submit_network_hook
    m._dismiss_known_info_overlays = lambda driver: None
    m._install_submit_network_hook = lambda driver: None
    try:
        return solver._process_current_tab_content("chapter", "tab", 0, 0)
    finally:
        m._dismiss_known_info_overlays = original_dismiss
        m._install_submit_network_hook = original_hook


def test_official_answers_fill_all():
    questions = [single_choice(1), single_choice(2)]
    solver = build_solver(questions, [True, True], official_answers=["A", "B"])
    ok = run(solver)
    assert ok is True, ok
    assert len(solver.executor.calls) == 2
    assert all(call["official"] is True for call in solver.executor.calls), \
        "官方答案填写时应处于 _exact_official_mode"
    assert solver.ai_client.asked == 0, "官方答案全部命中时不应请求 AI"
    assert solver.executor.submit_count == 1


def test_official_miss_falls_back_to_ai():
    questions = [single_choice(1), single_choice(2)]
    solver = build_solver(questions, [True, True], ai_response="1.A\n2.B")
    solver._extract_single_answer = lambda response, number: response.split()[number - 1].split(".")[1]
    ok = run(solver)
    assert ok is True, ok
    assert solver.ai_client.asked == 1, "未命中官方答案时应请求一次 AI"
    assert len(solver.executor.calls) == 2
    assert solver.executor.calls[0]["answer"] == "A"
    assert solver.executor.calls[1]["answer"] == "B"


def test_ai_empty_response_stops():
    questions = [single_choice(1)]
    solver = build_solver(questions, [True], ai_response="")
    ok = run(solver)
    assert ok is False, "AI 未返回答案应停止当前任务"
    assert solver.executor.submit_count == 0


def test_partial_fill_stops_after_ai():
    questions = [single_choice(1), single_choice(2)]
    solver = build_solver(questions, [True, False], ai_response="1.A\n2.B")
    solver._extract_single_answer = lambda response, number: response.split()[number - 1].split(".")[1]
    ok = run(solver)
    assert ok is False, "有题未填写成功应判失败"
    assert solver.executor.submit_count == 0


TESTS = [
    ("官方答案全命中 → 跳过 AI 并提交", test_official_answers_fill_all),
    ("官方答案未命中 → 回落 AI 作答", test_official_miss_falls_back_to_ai),
    ("AI 无答案 → 停止任务", test_ai_empty_response_stops),
    ("AI 部分失败 → 停止且不提交", test_partial_fill_stops_after_ai),
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
