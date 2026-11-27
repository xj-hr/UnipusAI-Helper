# -*- coding: utf-8 -*-
"""`_inspect_item` 分支抽离后的离线测试（D-03）。

四个题型分支已从 `AccuracyController._inspect_item()` 抽成独立方法：
`_inspect_dropdown_item` / `_inspect_fill_item` / `_inspect_match_item` / `_inspect_link_item`。
本文件直接调用这些方法，锁定它们的返回结构（`kind` 与关键字段）。

运行：
    python tests/test_inspect_item.py
"""
import os
import sys
import traceback
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unipus_helper.accuracy_control import AccuracyController  # noqa: E402


def controller():
    return object.__new__(AccuracyController)


def test_dropdown():
    q = SimpleNamespace(
        banked_blanks=[{"options": ["apple", "banana"]}, {"options": ["cat", "dog"]}],
        answer_count=2, banked_options=[],
    )
    result = controller()._inspect_dropdown_item(q, "1. apple\n2. cat", "DROPDOWN_SELECT")
    assert result and result["kind"] == "dropdown", result
    assert result["values"] == ["apple", "cat"], result["values"]
    assert result["perturbable"] == [0, 1], result["perturbable"]


def test_fill():
    q = SimpleNamespace(banked_blanks=[{"hint": "n."}, {"hint": "v."}],
                        answer_count=2, banked_options=["apple", "run"])
    result = controller()._inspect_fill_item(q, "1. apple\n2. run", "BANKED_CLOZE")
    assert result and result["kind"] == "text_blanks", result
    assert result["pool"] == ["apple", "run"], result["pool"]
    assert result["hints"] == ["n.", "v."], result["hints"]


def test_match():
    q = SimpleNamespace(inputs=[1, 2, 3], banked_blanks=[], options=[],
                        banked_options=["A", "B", "C"])
    result = controller()._inspect_match_item(q, "A B C", "PARAGRAPH_MATCH")
    assert result and result["kind"] == "letter_blanks", result
    assert result["values"] == ["A", "B", "C"], result["values"]
    assert result["perturbable"] == [0, 1, 2]


def test_link():
    q = SimpleNamespace(link_items=[{"side": "right"}, {"side": "left"}, {"side": "left"}])
    result = controller()._inspect_link_item(q, "1-A 2-B", "LINK_MATCH")
    assert result and result["kind"] == "link_match", result
    assert result["option_count"] == 2, result


def test_empty_answer_returns_none():
    q = SimpleNamespace(inputs=[1], banked_blanks=[], options=[], banked_options=["A", "B"])
    assert controller()._inspect_match_item(q, "   ", "MATCHING") is None


TESTS = [
    ("下拉选择 → dropdown", test_dropdown),
    ("填空 → text_blanks", test_fill),
    ("匹配 → letter_blanks", test_match),
    ("连线 → link_match", test_link),
    ("空答案 → None", test_empty_answer_returns_none),
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
