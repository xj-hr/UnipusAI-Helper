# -*- coding: utf-8 -*-
"""解析基线测试：用无头 Edge 加载页面样本，断言 `QuestionParser` 的输出。

用途：`_process_current_tab_content`（D-03）拆分时，唯一能拦住回归的手段。
页面样本来自 `logs/samples/sweep15_parse.html`（真实课程页，本地 gitignore），
以及 `tests/fixtures/choice_page_min.html`（同结构的最小合成页，可入库）。

运行：
    python tests/test_page_parse_baseline.py

无浏览器环境（如 CI）会打印 SKIP 并以 0 退出，不阻塞流水线。
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "choice_page_min.html")
REAL_SAMPLE = os.path.join(ROOT, "logs", "samples", "sweep15_parse.html")


def _edge_driver():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1400,900")
    options.add_argument("--allow-file-access-from-files")
    options.add_argument("--log-level=3")
    return webdriver.Edge(options=options)


def _parse_page(path):
    import UnipusAI_Helper as m

    driver = _edge_driver()
    try:
        driver.get("file:///" + path.replace("\\", "/"))
        parser = m.QuestionParser(driver)
        questions, directions = parser.parse_all()
        return questions, directions, parser.incomplete
    finally:
        driver.quit()


def test_fixture_three_single_choice():
    questions, directions, incomplete = _parse_page(FIXTURE)
    assert len(questions) == 3, f"应解析出 3 题，实际 {len(questions)}"
    assert incomplete is False, "不应标记为不完整"
    for index, question in enumerate(questions, start=1):
        assert question.q_type.name == "SINGLE_CHOICE", f"第 {index} 题类型={question.q_type}"
        assert str(question.text).startswith(f"{index}."), f"第 {index} 题题干={question.text!r}"
        assert len(question.options) == 3, f"第 {index} 题选项数={len(question.options)}"
        labels = [str(option.text).strip() for option in question.options]
        assert labels == ["True.", "False.", "Not given."], f"第 {index} 题选项={labels}"


def test_fixture_question_numbers_ordered():
    questions, _, _ = _parse_page(FIXTURE)
    numbers = [question.number for question in questions]
    assert numbers == sorted(numbers), f"题号应按出现顺序递增，实际 {numbers}"


def test_real_sample_if_present():
    if not os.path.exists(REAL_SAMPLE):
        print("      （未找到真实样本，跳过）")
        return
    questions, directions, incomplete = _parse_page(REAL_SAMPLE)
    assert len(questions) == 3, f"真实样本应解析出 3 题，实际 {len(questions)}"
    assert incomplete is False
    assert all(q.q_type.name == "SINGLE_CHOICE" for q in questions)
    assert all(len(q.options) == 3 for q in questions)
    assert "true" in (directions or "").lower(), f"direction 未取到：{directions!r}"


TESTS = [
    ("合成页：3 题 / 单选 / 3 选项", test_fixture_three_single_choice),
    ("合成页：题号按顺序", test_fixture_question_numbers_ordered),
    ("真实样本（若存在）", test_real_sample_if_present),
]


def main():
    try:
        driver = _edge_driver()
        driver.quit()
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP  无可用 Edge 浏览器：{type(exc).__name__}: {str(exc)[:100]}")
        return 0

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
