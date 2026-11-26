# -*- coding: utf-8 -*-
"""刷时长模块离线测试（S2 起）。

运行方式：
    python tests/test_time_brushing.py

覆盖范围：
  S2 纯逻辑层 —— 配置归一化（与 JS 侧语义一致）、站点层级 profile、注入脚本构建

设计原则：本文件只 import `time_brushing`（标准库模块），不 import UnipusAI_Helper，
因此不需要 torch / PyQt5 / 浏览器 / 网络 / API Key。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time_brushing as tb  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_JS = os.path.join(PROJECT_ROOT, "assets", "time_brushing_controller.js")


# ---------------------------------------------------------------- 工具

def _js_defaults_keys():
    """从控制器 JS 中抽出 `var DEFAULTS = {...}` 的键名集合（契约比对用）。"""
    with open(CONTROLLER_JS, "r", encoding="utf-8") as handle:
        source = handle.read()
    match = re.search(r"var DEFAULTS = \{(.*?)\n    \};", source, re.S)
    assert match, "未能在控制器 JS 中定位 DEFAULTS 块"
    return set(re.findall(r"^\s{8}(\w+):", match.group(1), re.M))


def _find_node():
    """定位可用的 node：优先 PATH，其次本机托管版本路径。"""
    found = shutil.which("node")
    if found:
        return found
    candidates = [
        r"C:\Users\xjykx\.workbuddy\binaries\node\versions\22.22.2-3\node.exe",
        r"C:\Program Files\nodejs\node.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------- S2 用例

def test_controller_defaults_contract_matches_python():
    """Python 侧选项键必须全部存在于 JS 侧 DEFAULTS（防止两侧配置契约漂移）。"""
    js_keys = _js_defaults_keys()
    options = tb.TimeBrushingSettings().as_controller_options()
    missing = sorted(set(options) - js_keys)
    assert not missing, f"以下选项 JS 侧 DEFAULTS 未定义：{missing}"


def test_num_matches_js_semantics():
    assert tb.num(3, 9) == 3
    assert tb.num(2.5, 9) == 2.5
    assert tb.num("3", 9) == 3
    assert tb.num(" 4.5 ", 9) == 4.5
    # JS: typeof true !== "number" → parseFloat("true") → NaN → fallback
    assert tb.num(True, 9) == 9, "布尔不得被当成数字（Python 的 bool 是 int 子类，必须显式排除）"
    assert tb.num("", 9) == 9
    assert tb.num("abc", 9) == 9
    assert tb.num(None, 9) == 9
    assert tb.num(float("nan"), 9) == 9
    assert tb.num(float("inf"), 9) == 9


def test_bool_value_matches_js_semantics():
    assert tb.bool_value(True, False) is True
    assert tb.bool_value(False, True) is False
    assert tb.bool_value("true", False) is True
    assert tb.bool_value("1", False) is True
    assert tb.bool_value("false", True) is False
    assert tb.bool_value("0", True) is False
    assert tb.bool_value("True", False) is False, "与 JS 严格相等语义一致（大小写敏感）"
    assert tb.bool_value(None, True) is True
    assert tb.bool_value(2, False) is True


def test_switch_interval_never_degenerates_to_zero():
    """源实现 D11：空串间隔会得到 0ms 疯狂点击，归一化后必须回退默认值。"""
    for bad in ("", "abc", None, 0, -5, False):
        settings = tb.TimeBrushingSettings({"switchInterval": bad})
        assert settings.switch_interval == tb.DEFAULTS["switchInterval"], f"bad={bad!r}"
    assert tb.TimeBrushingSettings({"switchInterval": "10"}).switch_interval == 10


def test_range_bounds_are_positive_and_ordered():
    settings = tb.TimeBrushingSettings({"rangeStart": -5, "rangeEnd": 3})
    assert settings.range_start == 1
    assert settings.range_end == 3

    settings = tb.TimeBrushingSettings({"rangeStart": 5, "rangeEnd": 2})
    assert settings.range_start == 5
    assert settings.range_end == 5, "结束单元小于开始单元时必须抬平，避免空区间"

    settings = tb.TimeBrushingSettings({"rangeStart": "2.7", "rangeEnd": "8"})
    assert settings.range_start == 3 and settings.range_end == 8


def test_switch_level_is_clamped_to_profile_depth():
    """层级数随 profile 变化，配置里的 3 不应再被当作恒定值。"""
    depth = len(tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]["levels"])
    assert tb.TimeBrushingSettings({"switchLevel": 99}).switch_level == depth
    assert tb.TimeBrushingSettings({"switchLevel": 0}).switch_level == 1
    assert tb.TimeBrushingSettings({"switchLevel": "-3"}).switch_level == 1
    assert tb.TimeBrushingSettings({"switchLevel": "2"}).switch_level == 2


def test_current_profile_levels_are_valid_js_options():
    settings = tb.TimeBrushingSettings()
    levels = settings.as_controller_options()["levels"]
    assert len(levels) == len(tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]["levels"])
    for level in levels:
        # clickTarget 是可选键（把点击落到层级元素内部的目标上）
        assert set(level) <= {"name", "selector", "activeClass", "clickTarget"}
        assert {"name", "selector", "activeClass"} <= set(level)
        assert level["selector"].strip()
        assert " " not in level["activeClass"], "activeClass 必须是单个类名（JS 用 classList.contains）"


def test_current_profile_anchors_range_on_micro_layer():
    """range 约束锚定在最外层；当前站点该层为侧栏 micro（每单元 16 个微课节点）。

    依据（2026-09-17 真机普查）：micro 96 个节点里有唯一 1 个带 pc-menu-activity（选中态），
    而 section（36 个）与 unit（6 个）**没有任何选中标记**，不能作为推进层。
    """
    profile = tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]
    settings = tb.TimeBrushingSettings()
    assert profile["rangeAnchor"] == profile["levels"][0]["name"]
    assert settings.level_names()[0] == profile["rangeAnchor"] == "micro"
    assert settings.chapters_per_unit == 16, "依据真机计数：96 micro / 6 unit = 16"
    assert settings.as_controller_options()["chaptersPerUnit"] == 16


def test_current_profile_excludes_levels_without_active_marker():
    """无选中态标记的层级（unit / section）不得进入 levels，否则推进退化为恒点第 0 项。"""
    profile = tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]
    names = [level["name"] for level in profile["levels"]]
    assert "section" not in names and "unit" not in names
    registered = {item["name"] for item in profile["nonAdvanceableLevels"]}
    assert {"unit", "section"} <= registered, "移出 levels 的层级必须在 nonAdvanceableLevels 登记原因"
    for level in tb.TimeBrushingSettings().as_controller_options()["levels"]:
        assert level["activeClass"], f"{level['name']} 缺少选中态类名"


def test_micro_layer_uses_field_verified_active_class():
    """侧栏选中态类名由真机普查定稿为 pc-menu-activity（否证 pc-menu-active 等候选）。"""
    settings = tb.TimeBrushingSettings()
    micro = {level["name"]: level for level in settings.as_controller_options()["levels"]}["micro"]
    assert micro["activeClass"] == "pc-menu-activity"
    assert micro["activeClass"] != "pc-menu-active", "pc-menu-active 全站 0 命中，是错误候选"


def test_verified_levels_use_dumped_active_classes():
    """已由落盘 + 真机双重验证的两层必须用实测类名，避免回归时被误改。"""
    settings = tb.TimeBrushingSettings()
    levels = {level["name"]: level for level in settings.as_controller_options()["levels"]}
    assert levels["activity"]["activeClass"] == "pc-header-tab-activity"
    assert levels["activity"]["selector"] == ".pc-header-tabs-container .pc-tab-row > .tab"
    assert levels["task"]["activeClass"] == "pc-header-task-activity"
    assert "pc-header-tasks-row > .pc-task" in levels["task"]["selector"]


def test_legacy_profile_keeps_source_selectors():
    """保留源油猴脚本的 3 层选择器作为对照（当前站点 0/23 命中）。"""
    settings = tb.TimeBrushingSettings({"profile": "legacy"})
    levels = settings.as_controller_options()["levels"]
    assert [level["name"] for level in levels] == ["chapter", "section", "tab"]
    assert levels[0]["selector"] == "#sidemenu li.group"
    assert levels[1]["selector"] == "#header .TabsBox li"
    assert levels[2]["selector"] == "[class*='circleTabsBox'] a"
    assert settings.profile_name == "legacy"


def test_unknown_profile_falls_back_to_default():
    settings = tb.TimeBrushingSettings({"profile": "not-a-profile"})
    assert settings.profile_name == tb.DEFAULT_PROFILE
    assert settings.level_names() == tb.TimeBrushingSettings().level_names()
    # 非字符串 profile 同样不得崩
    assert tb.TimeBrushingSettings({"profile": 123}).profile_name == tb.DEFAULT_PROFILE


def test_inject_script_embeds_source_options_and_autostart():
    script = tb.build_inject_script()
    assert "TimeBrushingController" in script
    assert "var __prevModule" in script, "必须有 module.exports 兜底取回"
    assert "module.exports" in script
    assert "instance.start();" in script
    assert f"window.{tb.JS_VAR} = instance;" in script
    assert script.strip().endswith("})();")
    # 关掉自动启动时不应出现 start 调用
    manual = tb.build_inject_script(autostart=False)
    assert "instance.start();" not in manual


def test_inject_script_options_json_round_trips():
    """注入脚本里的选项必须是可还原的 JSON（含中文/引号/反斜杠时不破坏脚本）。"""
    options = tb.TimeBrushingSettings().as_controller_options()
    options["dismissDialog"]["selector"] = "div[class*=\"dialog\"] \\ 中文'测试'"
    script = tb.build_inject_script(options=options)
    match = re.search(r"    var options = (\{.*?\});\n", script)
    assert match, "未能在注入脚本中定位 options 行"
    assert json.loads(match.group(1)) == options


def test_stop_and_status_scripts_shape():
    stop = tb.build_stop_script()
    assert "inst.stop(false)" in stop
    assert "inst.stop(true)" in tb.build_stop_script(finished=True)
    status = tb.build_status_script()
    assert "injected: false" in status and "tickCount" in status


def test_controller_source_missing_raises_actionable_error():
    try:
        tb.load_controller_source(path=os.path.join(PROJECT_ROOT, "assets", "not-exists.js"))
    except FileNotFoundError as exc:
        message = str(exc)
        assert "assets" in message and "spec" in message, f"报错需给出修复提示，实际：{message}"
    else:
        raise AssertionError("控制器源码缺失时必须抛错，而不是静默返回空串")


def test_probe_script_covers_every_level_and_candidate():
    profile = tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]
    script = tb.build_probe_script()
    payload = json.loads(re.search(r"    var cfg = (\{.*?\});\n", script).group(1))
    assert len(payload["levels"]) == len(profile["levels"])
    for expected, actual in zip(profile["levels"], payload["levels"]):
        assert actual["name"] == expected["name"]
        assert actual["selectors"] == list(expected["selectors"])
        assert actual["activeClasses"] == list(expected["activeClasses"])
    assert "querySelectorAll" in script


def _find_node():
    """定位可用的 node：优先 PATH，其次本机托管版本路径。"""
    found = shutil.which("node")
    if found:
        return found
    candidates = [
        r"C:\Users\xjykx\.workbuddy\binaries\node\versions\22.22.2-3\node.exe",
        r"C:\Program Files\nodejs\node.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _kind_of(script):
    """把注入脚本归类，便于断言调用序列。"""
    if "new Ctor(" in script:
        return "inject"
    if "logs: box" in script:          # 日志读取脚本（需在 status 之前判，二者都可能含 window 变量名）
        return "logs"
    if "inst.stop(" in script:
        return "stop(true)" if "inst.stop(true)" in script else "stop(false)"
    if "inst.start()" in script:
        return "start"
    if "inst.tickCount" in script:
        return "status"
    return "unknown"


class FakeScriptDriver:
    """只实现 execute_script 的假 driver：按脚本内容返回预设结果并记录调用序列。"""

    def __init__(self, status_sequence=None, raise_on=None, inject_ok=True, logs_sequence=None):
        self.calls = []
        self.status_sequence = list(status_sequence or [])
        self.logs_sequence = list(logs_sequence or [])
        self.raise_on = raise_on or ""
        self.inject_ok = inject_ok

    def execute_script(self, script):
        if self.raise_on and self.raise_on in script:
            raise RuntimeError("javascript error: 模拟驱动异常")
        self.calls.append((_kind_of(script), script))
        kind = _kind_of(script)
        if kind == "inject":
            if not self.inject_ok:
                return {"ok": False, "exists": False}
            return {"ok": True, "exists": True, "running": True, "levels": 4, "switchLevel": 4}
        if kind == "logs":
            if self.logs_sequence:
                return self.logs_sequence.pop(0)
            return {"logs": []}
        if kind == "stop(true)":
            return {"ok": True, "existed": True, "running": False}
        if kind == "stop(false)":
            return {"ok": True, "existed": True, "running": False}
        if kind == "start":
            return {"ok": True, "started": True, "running": True}
        if kind == "status":
            if self.status_sequence:
                return self.status_sequence.pop(0)
            return {"injected": True, "running": True, "finished": False, "ticks": 0}
        raise AssertionError(f"未预期的注入脚本：{script[:80]}")

    @property
    def kinds(self):
        return [kind for kind, _ in self.calls]

    def count(self, kind):
        return self.kinds.count(kind)


def _status(**kwargs):
    base = {"injected": True, "running": True, "finished": False, "ticks": 0}
    base.update(kwargs)
    return base


class _Log(object):
    """收集日志的替身（同时满足 callable 与可断言）。"""

    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(str(message))

    def joined(self):
        return "\n".join(self.messages)

    def has(self, keyword):
        return any(keyword in message for message in self.messages)


def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------- S3 用例

def test_mode_guard_is_exclusive_and_idempotent():
    guard = tb.ModeGuard()
    assert guard.owner is None
    assert guard.acquire("brushing") is True
    assert guard.acquire("brushing") is True, "同模式重复获取应幂等"
    assert guard.acquire("solving") is False
    assert guard.blocked_by("solving") == "brushing"
    assert guard.blocked_by("brushing") is None
    assert guard.release("solving") is False, "非持有者不得释放"
    assert guard.release("brushing") is True
    assert guard.acquire("solving") is True
    assert guard.release("solving") is True
    assert guard.owner is None


def test_session_inject_reports_configuration():
    log = _Log()
    session = tb.TimeBrushingSession(FakeScriptDriver(), None, log)
    result = session.inject(autostart=True)
    assert result["levels"] == 4
    assert session.injected is True
    assert log.has("已注入") and log.has("层"), log.joined()


def test_session_lifecycle_call_sequence():
    driver = FakeScriptDriver()
    session = tb.TimeBrushingSession(driver, None, _Log())
    session.inject(autostart=True)
    assert session.start() is True
    session.pause()
    assert session.resume() is True
    session.stop(finished=True)
    assert driver.kinds == ["inject", "status", "start", "stop(false)", "status", "start", "stop(true)"], \
        driver.kinds
    assert session.state() == tb.STATE_FINISHED


def test_session_status_marks_lost_when_instance_missing():
    driver = FakeScriptDriver(status_sequence=[{"injected": False, "running": False, "finished": False, "ticks": 0}])
    session = tb.TimeBrushingSession(driver, None, _Log())
    assert session.state() == tb.STATE_LOST
    session.status()
    assert session.state() == tb.STATE_LOST


def test_session_ensure_injected_reinjects_after_navigation():
    driver = FakeScriptDriver(status_sequence=[{"injected": False, "running": False, "finished": False, "ticks": 0}])
    log = _Log()
    session = tb.TimeBrushingSession(driver, None, log)
    injected_now = session.ensure_injected(autostart=True)
    assert injected_now is True
    assert driver.count("inject") == 1
    assert log.has("重新注入"), log.joined()

    # 已存在时不应重复注入
    driver2 = FakeScriptDriver(status_sequence=[_status()])
    session2 = tb.TimeBrushingSession(driver2, None, _Log())
    assert session2.ensure_injected() is False
    assert driver2.count("inject") == 0


def test_session_wraps_driver_exception_with_context():
    driver = FakeScriptDriver(raise_on="new Ctor(")
    session = tb.TimeBrushingSession(driver, None, _Log())
    try:
        session.inject()
    except tb.TimeBrushingError as exc:
        assert "注入刷时长控制器失败" in str(exc)
        assert "模拟驱动异常" in str(exc), "必须带上原始异常信息，不能吞掉"
    else:
        raise AssertionError("驱动异常必须转为 TimeBrushingError")


def test_session_inject_rejects_unexpected_result():
    driver = FakeScriptDriver(inject_ok=False)
    session = tb.TimeBrushingSession(driver, None, _Log())
    try:
        session.inject()
    except tb.TimeBrushingError as exc:
        assert "注入结果异常" in str(exc)
    else:
        raise AssertionError("注入返回值异常时不得静默通过")


def test_session_reset_drops_instance():
    driver = FakeScriptDriver()
    session = tb.TimeBrushingSession(driver, None, _Log())
    session.inject(autostart=True)
    session.reset()
    assert session.injected is False
    assert session.state() == tb.STATE_LOST
    assert driver.count("stop(false)") == 1


def test_runner_start_requires_enabled_flag():
    log = _Log()
    session = tb.TimeBrushingSession(FakeScriptDriver(), {"enabled": False}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log)
    assert runner.start() is False
    assert runner.running is False
    assert log.has("未启用"), log.joined()
    assert session.injected is False


def test_runner_start_blocked_by_solving_mode():
    guard = tb.ModeGuard()
    assert guard.acquire("solving") is True
    log = _Log()
    session = tb.TimeBrushingSession(FakeScriptDriver(), {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log, guard=guard)
    assert runner.start() is False
    assert guard.owner == "solving", "启动失败不得抢走答题方的占用"
    assert log.has("互斥"), log.joined()


def test_runner_start_holds_guard_and_stop_releases():
    guard = tb.ModeGuard()
    log = _Log()
    driver = FakeScriptDriver()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log, guard=guard, poll_interval=5.0)
    assert runner.start() is True
    assert runner.running is True
    assert guard.owner == "brushing"
    assert session.injected is True
    assert runner.start() is False, "重复启动应直接返回 False"
    assert runner.stop() is True
    assert guard.owner is None
    assert runner.running is False
    assert runner.state == tb.STATE_IDLE


def test_runner_stop_without_start_returns_false():
    log = _Log()
    session = tb.TimeBrushingSession(FakeScriptDriver(), {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log)
    assert runner.stop() is False
    assert session.injected is False


def test_runner_tick_once_reinjects_lost_controller():
    driver = FakeScriptDriver(status_sequence=[
        {"injected": False, "running": False, "finished": False, "ticks": 0}
    ])
    log = _Log()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log)
    state = runner.tick_once()
    assert state == tb.STATE_RUNNING
    assert driver.count("inject") == 1
    assert runner.polls == 1
    assert log.has("重新注入")


def test_runner_tick_once_finishes_on_controller_signal():
    driver = FakeScriptDriver(status_sequence=[_status(finished=True, running=False)])
    log = _Log()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log)
    assert runner.tick_once() == tb.STATE_FINISHED
    assert log.has("已完成")


def test_runner_tick_once_reports_paused():
    driver = FakeScriptDriver(status_sequence=[_status(running=False)])
    session = tb.TimeBrushingSession(driver, {"enabled": True}, _Log())
    runner = tb.TimeBrushingRunner(None, session=session, log=_Log())
    assert runner.tick_once() == tb.STATE_PAUSED


def test_runner_watchdog_reinjects_then_exits_on_finish():
    """看护线程：先遇到实例丢失（重注入），再收到 finished → 自行退出并释放占用。"""
    driver = FakeScriptDriver(status_sequence=[
        {"injected": False, "running": False, "finished": False, "ticks": 0},
        _status(finished=True, running=False),
    ])
    guard = tb.ModeGuard()
    log = _Log()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log, guard=guard, poll_interval=0.02)
    assert runner.start() is True
    assert _wait_until(lambda: not runner.running, timeout=5.0), "看护线程应在收到 finished 后退出"
    assert runner.state == tb.STATE_FINISHED
    assert guard.owner is None, "线程退出必须释放模式占用"
    assert driver.count("inject") == 2, f"应完成一次重注入，实际 inject={driver.count('inject')}"


def test_runner_watchdog_stops_after_consecutive_errors():
    """连续看护异常达上限即停（源实现 D7：无熔断会静默刷屏）。"""
    driver = FakeScriptDriver(raise_on="inst.tickCount")
    guard = tb.ModeGuard()
    log = _Log()
    session = tb.TimeBrushingSession(driver, {"enabled": True, "maxConsecutiveErrors": 3}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log, guard=guard, poll_interval=0.02)
    assert runner.start() is True
    assert _wait_until(lambda: not runner.running, timeout=5.0), "连续异常后看护线程必须退出"
    assert runner.state == tb.STATE_LOST
    assert guard.owner is None
    assert isinstance(runner.last_error, tb.TimeBrushingError)
    assert log.has("连续看护异常达上限"), log.joined()


def test_runner_pause_and_resume():
    driver = FakeScriptDriver()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, _Log())
    runner = tb.TimeBrushingRunner(None, session=session, log=_Log(), poll_interval=5.0)
    assert runner.start() is True
    assert runner.pause() is True
    assert runner.state == tb.STATE_PAUSED
    assert runner.resume() is True
    assert runner.state == tb.STATE_RUNNING
    assert "stop(false)" in driver.kinds
    runner.stop()


# ---------------------------------------------------------------- S4 配置块组装

def test_build_config_block_normalizes_and_keeps_unknown_keys():
    block = tb.build_config_block(
        {"switchLevel": "99", "switchInterval": "", "rangeStart": 3, "rangeEnd": 1, "enabled": "true"},
        {"maxIdleTicks": 7, "futureKey": "keep-me"},
    )
    depth = len(tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]["levels"])
    assert block["switchLevel"] == depth, "保存进文件的必须是运行时实际生效的值（已按 profile 层数夹紧）"
    assert block["switchInterval"] == tb.DEFAULTS["switchInterval"]
    assert block["rangeStart"] == 3 and block["rangeEnd"] == 3
    assert block["enabled"] is True
    assert block["maxIdleTicks"] == 7 and block["futureKey"] == "keep-me", "未暴露的子键必须保留"


def test_build_config_block_keeps_previous_when_editor_silent():
    previous = {"enabled": True, "switchLevel": 2, "switchInterval": 7, "randomInterval": False}
    block = tb.build_config_block({}, previous)
    assert block["enabled"] is True
    assert block["switchLevel"] == 2
    assert block["switchInterval"] == 7
    assert block["randomInterval"] is False
    # 未提供的子键回落到「profile 实测默认值」，而不是缺失
    assert block["chaptersPerUnit"] == tb.LEVEL_PROFILES[tb.DEFAULT_PROFILE]["chaptersPerUnit"]


def test_build_config_block_is_json_round_trippable():
    block = tb.build_config_block({"switchInterval": "2.5", "minIntervalMs": 45000}, None)
    restored = json.loads(json.dumps(block, ensure_ascii=False))
    assert restored == block
    assert restored["minIntervalMs"] == 45000
    assert tb.TimeBrushingSettings(restored).switch_interval == 2.5


def test_editor_fields_cover_runtime_settings_except_advanced():
    """编辑器暴露的字段须覆盖全部运行配置，仅允许留出「高级」项。"""
    exposed = set(tb.EDITOR_FIELDS)
    runtime = set(tb.DEFAULTS)
    assert exposed <= runtime, f"编辑器暴露了非配置键：{sorted(exposed - runtime)}"
    assert runtime - exposed == {"maxConsecutiveErrors", "maxIdleTicks"}, \
        "除两个高级项外，所有配置都必须能在界面上编辑（否则会被整份覆盖时丢失）"



def test_injected_script_runs_in_node_with_fake_dom():
    """端到端（离线）：把生成的注入脚本丢进带假 DOM 的 node 环境，验证真的能跑起来并完成一次切换。

    覆盖分析报告 §3 第 4 项的核心结论：UMD + execute_script 的函数体包装语义兼容。
    """
    node = _find_node()
    if not node:
        print("      SKIP 未找到 node，跳过端到端注入验证")
        return

    options = tb.TimeBrushingSettings({
        "switchLevel": 4,
        "switchInterval": 5,
        "minIntervalMs": 30000,
        "range": False,
        "loop": True,
    }).as_controller_options()
    inject = tb.build_inject_script(options=options, autostart=True)
    levels = options["levels"]

    def build_items(js_selector, active, active_class):
        """每个元素只携带**本层**的选中态类名（对齐真实 DOM）。

        旧实现给每个元素同时塞了三层的 active 类名，导致 `activeIndex(micro)` 恒为 -1
        （元素没有 micro 层的 `pc-menu-activity`）→ 被启动归位逻辑判为「未定位」并额外点击一次。
        """
        return (
            "[" + ", ".join(
                "mkItem(%s, %s, %s)" % (
                    json.dumps(js_selector),
                    "true" if i == active else "false",
                    json.dumps(active_class),
                )
                for i in range(3)
            ) + "]"
        )

    dom_entries = ",\n        ".join(
        "%s: %s" % (json.dumps(level["selector"]),
                    build_items(level["selector"], 0, level["activeClass"]))
        for level in levels
    )

    harness = """// 假 DOM + 假定时器，验证「注入脚本 → 控制器 → tick 点击」全链路
var recorded = [];
function mkItem(sel, active, activeClass) {
    var item = {
        selector: sel,
        classes: (active && activeClass) ? [activeClass] : [],
        clicked: 0,
        click: function () { item.clicked += 1; recorded.push(sel); },
    };
    item.classList = { contains: function (c) { return item.classes.indexOf(c) >= 0; } };
    return item;
}
var selectorMap = {
        %(dom)s
};
var fakeDocument = {
    querySelectorAll: function (sel) { return selectorMap[sel] || []; },
    querySelector: function (sel) { return (selectorMap[sel] || [])[0] || null; },
};
var timers = [];
globalThis.window = {
    document: fakeDocument,
    setTimeout: function (fn, delay) { timers.push(delay); return timers.length; },
    clearTimeout: function () {},
};
globalThis.window.window = globalThis.window;

%(inject_call)s

var inst = window.%(var)s;
if (!inst) throw new Error("注入后未找到控制器实例");
if (!injectResult || injectResult.ok !== true) throw new Error("注入脚本必须返回 {ok:true}，实际: " + JSON.stringify(injectResult));
if (inst.running !== true) throw new Error("自动启动失败，running=" + inst.running);
if (timers.length < 1) throw new Error("未排入定时器");
// start() 先排「首次切换」定时器，再排 dismissDialog 的关闭定时器
var firstDelay = timers[0];
if (!(firstDelay >= 30000 && firstDelay <= 300000)) throw new Error("首个切换间隔异常: " + firstDelay);
if (timers.indexOf(5000) < 0) throw new Error("未排入弹窗关闭定时器，实际: " + JSON.stringify(timers));

var taskSel = %(task_sel)s;
var acted = inst.tick();
if (!acted) throw new Error("tick 未产生任何动作");
if (recorded.length !== 1) throw new Error("每 tick 应只切换一次，实际: " + JSON.stringify(recorded));
if (recorded[0] !== taskSel) throw new Error("最内层未优先推进，实际点击: " + JSON.stringify(recorded));
if (selectorMap[taskSel][1].clicked !== 1) throw new Error("未点击 task 层的下一项");
if (selectorMap[taskSel][0].clicked !== 0) throw new Error("不应点击当前 active 项");
if (inst.tickCount !== 1) throw new Error("tickCount 应为 1，实际 " + inst.tickCount);

inst.stop(false);
if (inst.running !== false) throw new Error("stop() 后 running 应为 false");
console.log("E2E-OK ticks=" + inst.tickCount + " 首个间隔=" + firstDelay + "ms 点击=" + JSON.stringify(recorded));
""" % {
        "dom": dom_entries,
        "inject_call": "var injectResult = (new Function(%s))();" % json.dumps(inject),
        "var": tb.JS_VAR,
        "task_sel": json.dumps(levels[-1]["selector"]),
    }

    with tempfile.TemporaryDirectory(prefix="tb_e2e_") as tmp:
        harness_path = os.path.join(tmp, "e2e.js")
        with open(harness_path, "w", encoding="utf-8") as handle:
            handle.write(harness)
        completed = subprocess.run(
            [node, harness_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    if completed.returncode != 0:
        raise AssertionError(
            "node 端到端验证失败（exit=%s）\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (completed.returncode, completed.stdout, completed.stderr)
        )
    assert "E2E-OK" in (completed.stdout or ""), completed.stdout


# ---------------------------------------------------------------- S6 现场校准入口

def test_run_probe_returns_driver_result_and_passes_extras():
    class ProbeDriver:
        def __init__(self):
            self.scripts = []

        def execute_script(self, script):
            self.scripts.append(script)
            return {"profile": "current", "href": "http://x/y", "levels": [
                {"name": "section", "selectors": {"a": 3}, "activeClasses": {"pc-menu-active": 0}}
            ], "extraSelectors": {"z": 1}, "extraClasses": {"k": 2}}

    probe_driver = ProbeDriver()
    result = tb.run_probe(probe_driver, extra_selectors=["z"], extra_classes=["k"])
    assert result["levels"][0]["selectors"]["a"] == 3
    assert len(probe_driver.scripts) == 1
    assert '"extraSelectors":["z"]' in probe_driver.scripts[0].replace("\n", "")

    text = tb.format_probe_result(result)
    assert "section" in text and "a → 3" in text and "pc-menu-active → 0" in text
    assert "附加类名" in text


def test_run_probe_wraps_driver_exception():
    class BadDriver:
        def execute_script(self, script):
            raise RuntimeError("target closed")

    try:
        tb.run_probe(BadDriver())
    except tb.TimeBrushingError as exc:
        assert "现场校准脚本执行失败" in str(exc) and "target closed" in str(exc)
    else:
        raise AssertionError("驱动异常必须转为 TimeBrushingError")


def test_run_probe_rejects_non_dict_result():
    class WeirdDriver:
        def execute_script(self, script):
            return "not-a-dict"

    try:
        tb.run_probe(WeirdDriver())
    except tb.TimeBrushingError as exc:
        assert "返回异常" in str(exc)
    else:
        raise AssertionError("非 dict 返回值必须显式报错")

    assert "格式异常" in tb.format_probe_result(None)


def test_sidebar_census_script_targets_all_roles_and_back_queries_active_name():
    script = tb.build_sidebar_census_script()
    payload = json.loads(re.search(r"    var cfg = (\{.*?\});\n", script).group(1))
    assert payload["roles"] == list(tb.SIDEBAR_ROLES)
    assert "activity" in payload["activeTask"] and "activity" in payload["activeTab"]
    assert payload["nameSelector"] == ".pc-menu-node-name"
    assert 'div[data-role="' in script, "应按 role 拼接选择器"
    assert "closest" in script, "必须把同名节点回查到带 data-role 的祖先上"
    assert "onceOnly" in script
    assert script.strip().endswith("})();")


def test_run_sidebar_census_wraps_errors_and_rejects_non_dict():
    class BadDriver:
        def execute_script(self, script):
            raise RuntimeError("target window already closed")

    try:
        tb.run_sidebar_census(BadDriver())
    except tb.TimeBrushingError as exc:
        assert "侧栏普查脚本执行失败" in str(exc) and "already closed" in str(exc)
    else:
        raise AssertionError("驱动异常必须转为 TimeBrushingError")

    class WeirdDriver:
        def execute_script(self, script):
            return [1, 2, 3]

    try:
        tb.run_sidebar_census(WeirdDriver())
    except tb.TimeBrushingError as exc:
        assert "返回异常" in str(exc)
    else:
        raise AssertionError("非 dict 返回值必须显式报错")

    assert "格式异常" in tb.format_census_result("nope")


def test_format_census_result_surfaces_match_and_once_only():
    result = {
        "title": "读写教程3",
        "url": "http://x/pc.html",
        "active": {"task": "Reading", "tab": "Understanding"},
        "roles": {
            "section": {
                "count": 36,
                "classes": {"pc-menu-default": 35, "pc-menu-active": 1},
                "onceOnly": ["pc-menu-active"],
                "samples": [{"text": "Section A", "cls": "pc-slider-menu-section pc-menu-default"}],
            }
        },
        "matches": [{"name": "Reading", "role": "micro", "cls": "pc-slider-menu-micro pc-menu-active"}],
    }
    text = tb.format_census_result(result)
    assert "pc-menu-active" in text
    assert "★ 同名匹配" in text and "role=micro" in text
    assert "当前激活" in text and "Reading" in text and "Understanding" in text

    empty = tb.format_census_result({"roles": {}, "matches": [], "active": {}})
    assert "同名匹配: 无" in empty


def test_all_scripts_return_value_under_selenium_wrapping():
    """Selenium 的 execute_script 把脚本当**函数体**执行 —— 只有显式 return 才能拿到值。

    真机踩坑（2026-09-17）：脚本原本只写 `(function(){...})();`，返回恒为 undefined，
    Python 侧拿到 None → 「侧栏普查返回异常」/「注入结果异常」。此用例用
    `new Function(src)()` 复刻 Selenium 的包装语义，逐个脚本断言返回值确为对象。
    """
    node = _find_node()
    if not node:
        print("      SKIP 未找到 node，跳过脚本返回值验证")
        return

    options = tb.TimeBrushingSettings({"switchLevel": 4, "range": False}).as_controller_options()
    # 顺序有讲究：先在没有实例的环境里验证各脚本的"未注入"分支，
    # 最后才执行 inject，避免前面的断言被注入后的状态污染。
    scripts = {
        "status": tb.build_status_script(),
        "start": tb.build_start_script(),
        "stop": tb.build_stop_script(),
        "stop_finished": tb.build_stop_script(finished=True),
        "probe": tb.build_probe_script(),
        "census": tb.build_sidebar_census_script(),
        "inject": tb.build_inject_script(options=options, autostart=False),
    }
    for name, src in scripts.items():
        assert "return (function" in src, f"{name} 脚本缺少显式 return（Selenium 下必得 None）"

    harness = """// 复刻 Selenium execute_script 的包装语义：new Function(源码) 后直接调用
globalThis.location = { href: "http://example.invalid/pc.html" };
var fakeDocument = {
    title: "fake-title",
    querySelectorAll: function () { return []; },
    querySelector: function () { return null; },
};
globalThis.window = {
    document: fakeDocument,
    setTimeout: function () { return 1; },
    clearTimeout: function () {},
};
globalThis.window.window = globalThis.window;
globalThis.document = fakeDocument;  // 浏览器里 document 是全局，census 脚本直接用裸 document

var specs = %(specs)s;
var results = {};
specs.forEach(function (spec) {
    var value;
    try {
        value = (new Function(spec.src))();
    } catch (e) {
        throw new Error("脚本 " + spec.name + " 执行抛错: " + (e && e.message ? e.message : e));
    }
    if (value === undefined) {
        throw new Error("脚本 " + spec.name + " 返回 undefined —— 缺少显式 return");
    }
    if (typeof value !== "object" || value === null) {
        throw new Error("脚本 " + spec.name + " 返回非对象: " + JSON.stringify(value));
    }
    results[spec.name] = value;
});
console.log("SCRIPT-RETURNS " + JSON.stringify(results));
""" % {"specs": json.dumps([{"name": name, "src": src} for name, src in scripts.items()])}

    with tempfile.TemporaryDirectory(prefix="tb_ret_") as tmp:
        harness_path = os.path.join(tmp, "returns.js")
        with open(harness_path, "w", encoding="utf-8") as handle:
            handle.write(harness)
        completed = subprocess.run(
            [node, harness_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    if completed.returncode != 0:
        raise AssertionError(
            "node 返回值验证失败（exit=%s）\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (completed.returncode, completed.stdout, completed.stderr)
        )
    payload = json.loads((completed.stdout or "").split("SCRIPT-RETURNS ", 1)[1].strip())
    assert payload["inject"]["ok"] is True and payload["inject"]["exists"] is True
    assert payload["inject"]["levels"] == len(options["levels"])
    assert payload["status"]["injected"] is False, "未注入时 status 必须报告 injected=false"
    assert payload["start"]["ok"] is False and payload["start"]["reason"] == "not-injected"
    assert payload["stop"]["existed"] is False
    assert payload["stop_finished"]["ok"] is True
    assert "levels" in payload["probe"] and "roles" in payload["census"]
    assert payload["census"]["active"]["task"] is None


def test_click_mode_and_layer_miss_settings_normalized():
    """点击方式与层级空转阈值：默认多重事件派发；非法值不得穿透到 JS。"""
    default = tb.TimeBrushingSettings()
    assert default.click_mode == "events"
    assert default.max_layer_misses == 3
    assert tb.TimeBrushingSettings({"clickMode": "native"}).click_mode == "native"
    assert tb.TimeBrushingSettings({"clickMode": "whatever"}).click_mode == "events"
    assert tb.TimeBrushingSettings({"maxLayerMisses": "2"}).max_layer_misses == 2
    assert tb.TimeBrushingSettings({"maxLayerMisses": 0}).max_layer_misses == 1
    assert tb.TimeBrushingSettings({"maxLayerMisses": "abc"}).max_layer_misses == 3
    options = default.as_controller_options()
    assert options["clickMode"] == "events" and options["maxLayerMisses"] == 3


def test_activity_level_specifies_click_target_for_inner_container():
    """真机归因（2026-09-17）：点在 .tab 外层时 active 永不变化，故为 activity 层配内层点击目标。"""
    levels = {lv["name"]: lv for lv in tb.TimeBrushingSettings().as_controller_options()["levels"]}
    assert levels["activity"].get("clickTarget") == ".pc-tab-view-container"
    assert "clickTarget" not in levels["micro"], "micro 层无内层容器，不应配点击目标"
    assert "clickTarget" not in levels["task"]


# ---------------------------------------------------------------- S7 控制器日志透传

def test_build_logs_script_uses_selenium_return_wrapper():
    """日志脚本必须写成 `return (function(){...})();`，否则 Selenium 侧拿到 None。"""
    script = tb.build_logs_script()
    assert script.startswith("return (function"), script[:60]
    assert tb.JS_LOG_VAR in script, "脚本必须读写约定的日志变量名"


def test_inject_script_installs_onlog_collector():
    """注入脚本要挂 onLog 收集器：函数无法走 JSON，只能页面内就地定义。"""
    script = tb.build_inject_script(options=tb.TimeBrushingSettings(
        {"levels": [{"name": "micro", "selector": ".m", "activeClass": "pc-menu-activity"}]}
    ).as_controller_options())
    assert "options.onLog = function" in script, "未安装 onLog 收集器"
    assert f"window.{tb.JS_LOG_VAR} = []" in script, "未初始化日志缓冲"
    assert f"box.length > {tb.JS_LOG_MAX}" in script, "日志缓冲缺少上限保护"


def test_session_drain_logs_returns_entries():
    driver = FakeScriptDriver(logs_sequence=[{"logs": [
        {"t": 1, "msg": "当前位置 91 不在范围 [0, 15] 内，归位到 0"},
        {"t": 2, "msg": "micro 层点击后 active 未变化（1/3）"},
    ]}])
    session = tb.TimeBrushingSession(driver, None, _Log())
    entries = session.drain_logs()
    assert len(entries) == 2, entries
    assert entries[0]["msg"] == "当前位置 91 不在范围 [0, 15] 内，归位到 0"
    assert driver.count("logs") == 1


def test_session_drain_logs_swallows_driver_errors():
    """日志通道失败不得影响挂机主流程：异常应被吞掉并返回空列表。"""
    driver = FakeScriptDriver(raise_on="logs: box")
    session = tb.TimeBrushingSession(driver, None, _Log())
    assert session.drain_logs() == []


def test_session_drain_logs_tolerates_bad_shape():
    """返回结构异常（非 list）时返回空列表，而不是把脏数据抛给调用方。"""
    driver = FakeScriptDriver(logs_sequence=[{"logs": "oops"}])
    session = tb.TimeBrushingSession(driver, None, _Log())
    assert session.drain_logs() == []


def test_runner_forwards_controller_logs_to_python_log():
    """控制器内部日志（启动归位 / 层级点击无效）必须出现在 Python 日志里。"""
    driver = FakeScriptDriver(logs_sequence=[
        {"logs": [{"t": 1, "msg": "当前位置 91 不在范围 [0, 15] 内，归位到 0"}]},
        {"logs": [{"t": 2, "msg": "micro 层点击后 active 未变化（1/3）"}]},
        {"logs": []},
    ])
    log = _Log()
    session = tb.TimeBrushingSession(driver, {"enabled": True}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log, poll_interval=5.0)
    runner.start()
    assert log.has("归位到 0"), log.joined()
    assert "[页面]" in log.joined(), log.joined()
    runner.tick_once()
    assert log.has("active 未变化"), log.joined()


def test_describe_scope_translates_range_to_sections():
    """GUI 日志里的「刷哪几节」由 describe_scope 生成，语义必须是节而非单元。"""
    settings = tb.TimeBrushingSettings({"range": True, "rangeStart": 1, "rangeEnd": 2})
    assert tb.describe_scope(settings) == "第 1–2 节（共 2 节）", tb.describe_scope(settings)
    single = tb.TimeBrushingSettings({"range": True, "rangeStart": 3, "rangeEnd": 3})
    assert tb.describe_scope(single) == "第 3 节（共 1 节）", tb.describe_scope(single)


def test_describe_scope_marks_unrestricted_range():
    settings = tb.TimeBrushingSettings({"range": False})
    text = tb.describe_scope(settings)
    assert "未限定范围" in text, text


def test_runner_start_reports_scope_and_levels():
    driver = FakeScriptDriver()
    log = _Log()
    session = tb.TimeBrushingSession(
        driver, {"enabled": True, "range": True, "rangeStart": 1, "rangeEnd": 1}, log)
    runner = tb.TimeBrushingRunner(None, session=session, log=log,
                                   guard=tb.ModeGuard(), poll_interval=5.0)
    runner.start()
    joined = log.joined()
    assert "本次范围" in joined, joined
    assert "第 1 节" in joined, joined
    assert "每次成功切换都会输出当前节次" in joined, joined


TESTS = [
    # ---- S2 纯逻辑层 ----
    test_controller_defaults_contract_matches_python,
    test_num_matches_js_semantics,
    test_bool_value_matches_js_semantics,
    test_switch_interval_never_degenerates_to_zero,
    test_range_bounds_are_positive_and_ordered,
    test_switch_level_is_clamped_to_profile_depth,
    test_current_profile_levels_are_valid_js_options,
    test_current_profile_anchors_range_on_micro_layer,
    test_current_profile_excludes_levels_without_active_marker,
    test_micro_layer_uses_field_verified_active_class,
    test_click_mode_and_layer_miss_settings_normalized,
    test_activity_level_specifies_click_target_for_inner_container,
    test_verified_levels_use_dumped_active_classes,
    test_legacy_profile_keeps_source_selectors,
    test_unknown_profile_falls_back_to_default,
    test_inject_script_embeds_source_options_and_autostart,
    test_inject_script_options_json_round_trips,
    test_stop_and_status_scripts_shape,
    test_controller_source_missing_raises_actionable_error,
    test_probe_script_covers_every_level_and_candidate,
    # ---- S3 注入器与运行宿主 ----
    test_mode_guard_is_exclusive_and_idempotent,
    test_session_inject_reports_configuration,
    test_session_lifecycle_call_sequence,
    test_session_status_marks_lost_when_instance_missing,
    test_session_ensure_injected_reinjects_after_navigation,
    test_session_wraps_driver_exception_with_context,
    test_session_inject_rejects_unexpected_result,
    test_session_reset_drops_instance,
    test_runner_start_requires_enabled_flag,
    test_runner_start_blocked_by_solving_mode,
    test_runner_start_holds_guard_and_stop_releases,
    test_runner_stop_without_start_returns_false,
    test_runner_tick_once_reinjects_lost_controller,
    test_runner_tick_once_finishes_on_controller_signal,
    test_runner_tick_once_reports_paused,
    test_runner_watchdog_reinjects_then_exits_on_finish,
    test_runner_watchdog_stops_after_consecutive_errors,
    test_runner_pause_and_resume,
    # ---- S4 配置块组装 ----
    test_build_config_block_normalizes_and_keeps_unknown_keys,
    test_build_config_block_keeps_previous_when_editor_silent,
    test_build_config_block_is_json_round_trippable,
    test_editor_fields_cover_runtime_settings_except_advanced,
    # ---- S6 现场校准入口 ----
    test_run_probe_returns_driver_result_and_passes_extras,
    test_run_probe_wraps_driver_exception,
    test_run_probe_rejects_non_dict_result,
    # ---- S6b 侧栏选中态普查 ----
    test_sidebar_census_script_targets_all_roles_and_back_queries_active_name,
    test_run_sidebar_census_wraps_errors_and_rejects_non_dict,
    test_format_census_result_surfaces_match_and_once_only,
    # ---- 端到端（离线，需 node） ----
    test_all_scripts_return_value_under_selenium_wrapping,
    test_injected_script_runs_in_node_with_fake_dom,
    # ---- S7 控制器日志透传 ----
    test_build_logs_script_uses_selenium_return_wrapper,
    test_inject_script_installs_onlog_collector,
    test_session_drain_logs_returns_entries,
    test_session_drain_logs_swallows_driver_errors,
    test_session_drain_logs_tolerates_bad_shape,
    test_runner_forwards_controller_logs_to_python_log,
    # ---- S8 进度日志（节次标识）----
    test_describe_scope_translates_range_to_sections,
    test_describe_scope_marks_unrestricted_range,
    test_runner_start_reports_scope_and_levels,
]


def main():
    failed = 0
    for test in TESTS:
        name = test.__name__
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
