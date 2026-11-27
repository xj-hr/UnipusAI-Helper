# -*- coding: utf-8 -*-
"""遍历课程单元，采样页面 HTML，直到命中题目页（用于建立解析回归基线）。

背景：`_process_current_tab_content`（455 行）要拆分，必须先有「真实题目页 → 解析结果」
的基线；而项目里没有现成的题目页样本。本脚本负责自动翻单元、进任务、存页面。

安全约束（脚本内已实现，勿随意去掉）：
  1. `AnswerExecutor.submit` / `submit_button` 被替换为直接返回 True —— **不会真正提交**，
     页面上填充的选项会随页面跳转丢弃，不写学习记录；
  2. `AudioHandler.handle` / `VideoHandler.handle` 置空 —— 不播放音视频，避免真实计时；
  3. 只做导航与解析，不修改课程结构。

用法：
    python scripts/sweep_question_pages.py --url "<课程内容页 URL>"
    python scripts/sweep_question_pages.py --url "..." --max-units 6 --tasks-per-unit 3

产出：`logs/samples/sweepNN_parse.html`（解析前）与 `sweepNN_after.html`（解析后），
命中题目页时打印路径并以退出码 0 结束；未命中返回 1。

注意：课件页的单元在侧栏（`pc-slider-menu-unit`），与课程首页的单元 Tab
（`unitTabScrollContainer`，`select_course_unit()` 的目标）不是同一套结构。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import UnipusAI_Helper as m  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402

#: 题目页特征：新旧播放器的容器类名都算
QUESTION_PAT = re.compile(
    r"question-common-abs-reply|option-wrap|option-wrapper|fe-scoop|question-inputbox", re.I)

CLICK_JS = """
    const el = arguments[0];
    ['mouseover','mousedown','mouseup','click'].forEach(t =>
        el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, view:window})));
    return true;
"""


def dump(driver, out_dir, seq, tag):
    """保存当前页面；返回 (路径, 是否含题目结构)。"""
    seq[0] += 1
    try:
        html = driver.page_source
    except Exception as exc:  # noqa: BLE001
        print(f"[dump] 失败：{type(exc).__name__}: {exc}")
        return None, False
    path = os.path.join(out_dir, f"sweep{seq[0]:02d}_{tag}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    has_question = bool(QUESTION_PAT.search(html))
    print(f"[dump] {os.path.basename(path)} {len(html) // 1024}KB 题目={has_question}")
    return path, has_question


def patch_for_sampling():
    """拦提交、停播放：只读采样，不改学习记录。"""
    m.AnswerExecutor.submit = lambda self, *a, **k: True
    if hasattr(m.AnswerExecutor, "submit_button"):
        m.AnswerExecutor.submit_button = lambda self, *a, **k: True
    for name in ("AudioHandler", "VideoHandler"):
        cls = getattr(m, name, None)
        if cls is not None:
            cls.handle = lambda self, q: True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="课程内容页 URL（浏览器地址栏复制）")
    parser.add_argument("--max-units", type=int, default=4, help="最多遍历几个单元")
    parser.add_argument("--tasks-per-unit", type=int, default=2, help="每个单元最多试几个任务")
    parser.add_argument("--task-seconds", type=float, default=90.0, help="单个任务的处理上限（秒）")
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "logs", "samples"), help="样本输出目录")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    seq = [0]
    hits = []

    bot = m.UCampusBot(os.path.join(BASE_DIR, "config.json"), skip_check=True)
    solver = m.AISolver(bot.driver, bot.config)
    driver = bot.driver
    try:
        print("登录：", bot._login())
        driver.get(args.url)
        time.sleep(6)
        dump(driver, args.out, seq, "course")

        from unipus_helper.native_ui import NativeModernGUI
        ctrl = NativeModernGUI(driver, solver, bot, vars(m))
        ctrl._ready = True
        patch_for_sampling()

        original = m.AISolver._process_current_tab_content

        def wrapped(self, *a, **k):
            path, has_q = dump(driver, args.out, seq, "parse")
            if has_q and path:
                hits.append(path)
            result = original(self, *a, **k)
            path2, has_q2 = dump(driver, args.out, seq, "after")
            if has_q2 and path2:
                hits.append(path2)
            return result

        m.AISolver._process_current_tab_content = wrapped

        units = driver.find_elements(By.CSS_SELECTOR, ".pc-slider-menu-unit")
        print(f"单元数：{len(units)}")
        for unit_index, unit in enumerate(units[: args.max_units]):
            if hits:
                break
            label = (unit.text or "").strip().splitlines()[:1]
            print(f"\n=== 单元 {unit_index} {label} ===")
            try:
                driver.execute_script(CLICK_JS, unit)
            except Exception as exc:  # noqa: BLE001
                print("  切换失败：", type(exc).__name__, str(exc)[:80])
                continue
            time.sleep(3)

            ctrl.start_action("scan")
            for _ in range(30):
                if not ctrl.snapshot()["busy"]:
                    break
                time.sleep(2)
            tasks = [t for t in ctrl.snapshot()["tasks"] if t.get("status") != "done"]
            print("  任务：", len(tasks), [t["title"][:16] for t in tasks[:4]])
            for task in tasks[: args.tasks_per_unit]:
                if hits:
                    break
                ctrl.set_selection([t["id"] for t in ctrl.snapshot()["tasks"]], False)
                ctrl.set_selection([task["id"]], True)
                print("  运行：", task["title"][:20])
                ctrl.start_action("run")
                started = time.time()
                while time.time() - started < args.task_seconds:
                    if hits or not ctrl.snapshot()["busy"]:
                        break
                    time.sleep(2)
                ctrl.stop()
                time.sleep(2)
    finally:
        if driver:
            driver.quit()

    if hits:
        print("\n命中题目页：")
        for path in hits:
            print("  ", path)
        return 0
    print("\n未命中题目页（本课程的单元可能都是音视频材料）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
