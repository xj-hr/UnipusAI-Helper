# -*- coding: utf-8 -*-
"""刷时长模块（独立模块，方案 A）—— 纯逻辑层。

职责边界（依据 `docs/刷时长模块集成可行性分析报告.md`）：

1. **与答题链路零耦合**：本模块不 import `UnipusAI_Helper`，也不依赖 torch / PyQt5 / selenium，
   只使用标准库 → 可离线单元测试（`tests/test_time_brushing.py`）。
2. **只在 Python 侧做四件事**：归一化配置 → 生成注入脚本 → 注入并启停 → 看护线程兜底重注入。
   真正的定时调度由 `assets/time_brushing_controller.js`（零依赖 UMD，22 项行为测试通过）
   在页面上下文内完成；Python 侧**不参与定时**，避免双层定时器互相干扰。
3. **层级选择器按站点 profile 配置化**：源油猴脚本（`F:\\UnipusHelper` v1.2.0）的
   `#sidemenu li.group` / `#header .TabsBox li` / `[class*='circleTabsBox'] a`
   在当前站点 23 份真实页面上命中 **0/23**，因此绝不硬编码，改由 `LEVEL_PROFILES` 提供，
   并附 `build_probe_script()` 供现场一次性校准选择器与选中态类名。

术语：JS 控制器把层级数组的第 0 项视为「最外层」（受 `range` / `loop` 约束），
索引越大越靠内；`switchLevel` 语义为「每 tick 最多推进到第几层」（1 = 只推最外层）。
"""

import json
import os
import sys
import threading

__all__ = [
    "MODULE_VERSION",
    "CONTROLLER_RELATIVE_PATH",
    "DEFAULTS",
    "LEVEL_PROFILES",
    "DEFAULT_PROFILE",
    "JS_VAR",
    "JS_LOG_VAR",
    "JS_LOG_MAX",
    "TimeBrushingError",
    "TimeBrushingSettings",
    "ModeGuard",
    "TimeBrushingSession",
    "TimeBrushingRunner",
    "EDITOR_FIELDS",
    "build_config_block",
    "num",
    "bool_value",
    "clamp",
    "load_controller_source",
    "resolve_profile",
    "resolve_levels",
    "describe_scope",
    "build_inject_script",
    "build_start_script",
    "build_stop_script",
    "build_status_script",
    "build_logs_script",
    "build_probe_script",
    "run_probe",
    "format_probe_result",
    "SIDEBAR_ROLES",
    "build_sidebar_census_script",
    "run_sidebar_census",
    "format_census_result",
]

MODULE_VERSION = "1.0.0"

#: 控制器 JS 相对项目根的路径（打包后经 sys._MEIPASS 解析，见 `load_controller_source`）
CONTROLLER_RELATIVE_PATH = os.path.join("assets", "time_brushing_controller.js")

#: 与 JS 侧 `TimeBrushingController.DEFAULTS` 对齐的 Python 默认值。
#: 键名刻意与 JS 选项名一致，便于逐项比对（tests/test_time_brushing.py 有对应断言）。
DEFAULTS = {
    "enabled": False,
    "switchLevel": 3,
    "switchInterval": 5,       # 分钟
    "randomInterval": True,
    "range": True,
    "rangeStart": 1,
    "rangeEnd": 8,
    "chaptersPerUnit": 6,      # 仅作最后兜底；current profile 的实际值为 16
    "loop": True,
    "minIntervalMs": 30000,
    "maxConsecutiveErrors": 3,
    "maxIdleTicks": 5,
    # 点击方式：本站单次 el.click() 点不动一级 Tab（2026-09-17 真机归因），默认改用多重事件派发
    "clickMode": "events",
    # 某层连续「点了但 active 没变」达此次数即禁用该层，避免空转
    "maxLayerMisses": 3,
    "profile": "current",
}

#: 选中态类名候选项的说明（现场校准用，不影响运行逻辑）
_ACTIVE_UNVERIFIED = "未验证：23 份真实落盘中不存在该类名，需用 build_probe_script() 现场探测"

# ---------------------------------------------------------------------------- 站点层级 profile
#
# 每个 profile 是一组「从外到内」的层级定义，字段：
#   name         层级标识
#   selectors    候选 CSS 选择器（运行时用 ", " 连成 CSS 组，命中任一即可）
#   activeClasses 选中态类名候选（JS 只接受单一类名 → 取第一个；其余交给 probe 校准）
#   verified     是否由真实页面落盘验证过
#   note         依据说明
LEVEL_PROFILES = {
    # 当前站点（2026-09-17 由 logs/ 下 23 份真实落盘确认）
    "current": {
        "description": "U 校园 AI 版当前界面（pc-header-* / pc-slider-* 体系）",
        # 2026-09-17 真机普查定稿（logs/time_brushing_live_20260917_124025.json）：
        #   · micro 96 个节点：pc-menu-default×95 + **pc-menu-activity×1** ← 唯一标记，即选中态
        #   · section 36 个节点：全部 pc-menu-default，**无任何标记** → 不能作为推进层
        #     （控制器的 advanceLevel/advanceChapter 靠 active 类找"当前项"，无标记会退化成
        #      每 tick 都点第 0 项）→ 故 section 移出 levels，仅在此登记
        #   · unit 6 个节点：只有 pc-slider-menu-unit，同样无标记
        #   · 否证：pc-menu-active / pc-menu-current / selected / active / current 全站 0 命中
        "levels": [
            {
                "name": "micro",
                "selectors": [
                    '.pc-slier-menu-container .pc-slider-content-menu div[data-role="micro"]',
                    ".pc-slider-menu-micro",
                ],
                "activeClasses": ["pc-menu-activity"],
                "verified": True,
                "note": "侧栏「微课/任务节点」层，承担原先的『章节』语义（受 range 约束）；"
                        "选中态 pc-menu-activity 由 2026-09-17 真机普查确认（96 个节点中唯一 1 个）",
            },
            {
                "name": "activity",
                "selectors": [".pc-header-tabs-container .pc-tab-row > .tab"],
                "activeClasses": ["pc-header-tab-activity"],
                # 真机归因（2026-09-17）：点在 .tab 外层时 active 永不变化，怀疑处理器绑在内层
                # .pc-tab-view-container 上（落盘中该 div 是 .tab 的直接子元素）；找不到时自动退回外层
                "clickTarget": ".pc-tab-view-container",
                "verified": True,
                "note": "顶部一级 Tab（Reading / Understanding …），选中态 23/23 落盘 + 真机确认",
            },
            {
                "name": "task",
                "selectors": [
                    ".pc-header-tasks-container .pc-header-tasks-row > .pc-task",
                    ".pc-header-tasks-row > .pc-task",
                ],
                "activeClasses": ["pc-header-task-activity"],
                "verified": True,
                "note": "顶部二级 Tab（单元内任务），选中态 23/23 落盘 + 真机确认；"
                        "注意当前单元下可能只有 1 项，此时该层不参与推进",
            },
        ],
        #: 存在但**不可作为推进层**的层级（无选中态标记），登记以免后人重蹈覆辙
        "nonAdvanceableLevels": [
            {"name": "unit", "selector": 'div[data-role="unit"]',
             "note": "6 个节点只有 pc-slider-menu-unit，无任何选中标记"},
            {"name": "section", "selector": 'div[data-role="section"]',
             "note": "36 个节点全部 pc-menu-default，无任何选中标记"},
        ],
        "dismissDialog": {
            "selector": "div[class*='dialog-header-pc']",
            "delayMs": 5000,
        },
        "rangeAnchor": "micro",
        #: 当前站点 96 个 micro / 6 个 unit = 16（2026-09-17 真机实测计数）
        "chaptersPerUnit": 16,
    },
    # 源油猴脚本站点（保留作为对照，勿用于当前站点）
    "legacy": {
        "description": "源油猴脚本 v1.2.0 所依赖的旧版界面（#sidemenu / #header .TabsBox）",
        "levels": [
            {
                "name": "chapter",
                "selectors": ["#sidemenu li.group"],
                "activeClasses": ["active"],
                "verified": False,
                "note": "当前站点 0/23 命中，仅作回归对照",
            },
            {
                "name": "section",
                "selectors": ["#header .TabsBox li"],
                "activeClasses": ["active"],
                "verified": False,
                "note": "当前站点 0/23 命中，仅作回归对照",
            },
            {
                "name": "tab",
                "selectors": ["[class*='circleTabsBox'] a"],
                "activeClasses": ["selected"],
                "verified": False,
                "note": "当前站点 0/23 命中，仅作回归对照",
            },
        ],
        "dismissDialog": {
            "selector": "div[class*='dialog-header-pc']",
            "delayMs": 5000,
        },
        "rangeAnchor": "chapter",
    },
}

DEFAULT_PROFILE = "current"


# ---------------------------------------------------------------------------- 归一化工具
# 语义刻意与 JS 侧 num() / bool() 完全一致：同一份配置字典会被原样交给页面内的控制器，
# 两侧若语义不同就会出现「Python 认为开了、JS 认为没开」的静默分歧。

def num(value, fallback):
    """JS `num()` 等价实现：非数字（含布尔、空串、None）一律回退默认值。

    注意：Python 里 `bool` 是 `int` 的子类，若不显式排除会得到 `num(True) == 1`，
    而 JS 侧 `typeof true !== "number"` → `parseFloat("true")` → `NaN` → 回退默认值。
    """
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        try:
            result = float(str(value).strip())
        except (TypeError, ValueError):
            return fallback
    if result != result or result in (float("inf"), float("-inf")):  # NaN / Inf
        return fallback
    return result


def bool_value(value, fallback):
    """JS `bool()` 等价实现。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value in ("true", "1")
    if value is None:
        return fallback
    return bool(value)


def clamp(value, low, high):
    return min(max(value, low), high)


# ---------------------------------------------------------------------------- 控制器源码加载

_SOURCE_CACHE = {}


def controller_path(relative_path=None):
    """解析控制器 JS 的绝对路径（开发态用项目根，冻结态用 sys._MEIPASS）。"""
    relative_path = relative_path or CONTROLLER_RELATIVE_PATH
    if os.path.isabs(relative_path):
        return relative_path
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


def load_controller_source(path=None):
    """读取控制器 JS 源码；文件缺失时抛出带修复提示的异常，避免静默失败。"""
    resolved = controller_path(path)
    if resolved in _SOURCE_CACHE:
        return _SOURCE_CACHE[resolved]
    if not os.path.exists(resolved):
        raise FileNotFoundError(
            f"刷时长控制器源码缺失：{resolved}\n"
            f"修复：确认 {CONTROLLER_RELATIVE_PATH} 存在；打包时需在 spec 的 datas 中包含 assets/ 目录。"
        )
    with open(resolved, "r", encoding="utf-8") as handle:
        source = handle.read()
    if "TimeBrushingController" not in source:
        raise ValueError(f"控制器源码内容异常（未找到 TimeBrushingController）：{resolved}")
    _SOURCE_CACHE[resolved] = source
    return source


# ---------------------------------------------------------------------------- 层级解析

def resolve_profile(profile=None):
    """按名称取 profile；未知名称回退默认并返回 (profile_dict, resolved_name)。"""
    name = profile if isinstance(profile, str) else None
    if name not in LEVEL_PROFILES:
        name = DEFAULT_PROFILE
    return LEVEL_PROFILES[name], name


def resolve_levels(profile=None, switch_level=None):
    """生成 JS 侧 `levels` 选项，并返回生效的 switchLevel。

    返回 (levels, effective_switch_level, profile_name)：
      levels   —— [{"name", "selector", "activeClass"}, ...]，从外到内
      switchLevel —— 夹紧到 [1, len(levels)]（层级数随 profile 变化，配置里的 3 不再恒定）
    """
    profile_data, profile_name = resolve_profile(profile)
    levels = []
    for level in profile_data["levels"]:
        selectors = [s for s in level.get("selectors", []) if s]
        if not selectors:
            continue
        active_classes = [c for c in level.get("activeClasses", []) if c]
        item = {
            "name": level["name"],
            "selector": ", ".join(selectors),
            "activeClass": active_classes[0] if active_classes else "active",
        }
        # 可选：把点击落到层级元素内部的目标上（本站一级 Tab 的处理器疑似绑在内层容器）
        if level.get("clickTarget"):
            item["clickTarget"] = level["clickTarget"]
        levels.append(item)
    if not levels:
        raise ValueError(f"profile「{profile_name}」未定义任何有效层级（selectors 全为空）")

    raw_level = int(round(num(switch_level, DEFAULTS["switchLevel"])))
    effective = int(clamp(raw_level, 1, len(levels)))
    return levels, effective, profile_name


# ---------------------------------------------------------------------------- 配置归一化

class TimeBrushingSettings:
    """刷时长运行配置（归一化后的不可变视图）。

    与 `UnipusAI_Helper.Config` 解耦：后者只负责把 config.json 里的 `time_brushing`
    字典交给 `from_mapping()`，本类不反向依赖。
    """

    KEYS = (
        "enabled", "switchLevel", "switchInterval", "randomInterval", "range",
        "rangeStart", "rangeEnd", "chaptersPerUnit", "loop", "minIntervalMs",
        "maxConsecutiveErrors", "maxIdleTicks", "clickMode", "maxLayerMisses", "profile",
    )

    def __init__(self, raw=None):
        data = dict(DEFAULTS)
        provided = set()
        if isinstance(raw, dict):
            provided = set(raw)
            for key in self.KEYS:
                if key in raw:
                    data[key] = raw[key]

        self.enabled = bool_value(data.get("enabled"), DEFAULTS["enabled"])
        self.switch_interval = num(data.get("switchInterval"), DEFAULTS["switchInterval"])
        if not self.switch_interval > 0:  # 防 "" / "abc" → 0 ms 疯狂点击（源实现 D11）
            self.switch_interval = DEFAULTS["switchInterval"]
        self.random_interval = bool_value(data.get("randomInterval"), DEFAULTS["randomInterval"])
        self.range = bool_value(data.get("range"), DEFAULTS["range"])
        self.loop = bool_value(data.get("loop"), DEFAULTS["loop"])
        self.min_interval_ms = max(1000, num(data.get("minIntervalMs"), DEFAULTS["minIntervalMs"]))
        self.max_consecutive_errors = max(1, int(round(num(data.get("maxConsecutiveErrors"),
                                                          DEFAULTS["maxConsecutiveErrors"]))))
        self.max_idle_ticks = max(1, int(round(num(data.get("maxIdleTicks"),
                                                  DEFAULTS["maxIdleTicks"]))))
        self.click_mode = data.get("clickMode") if data.get("clickMode") == "native" else DEFAULTS["clickMode"]
        self.max_layer_misses = max(1, int(round(num(data.get("maxLayerMisses"),
                                                       DEFAULTS["maxLayerMisses"]))))
        self.profile = data.get("profile") if isinstance(data.get("profile"), str) else DEFAULT_PROFILE

        # 每单元节点数随站点/课程而变：配置未显式给出时，以 profile 的实测值为准
        profile_data, self.profile_name = resolve_profile(self.profile)
        if "chaptersPerUnit" in provided:
            chapters_value = data.get("chaptersPerUnit")
        else:
            chapters_value = profile_data.get("chaptersPerUnit", DEFAULTS["chaptersPerUnit"])
        self.chapters_per_unit = max(1, int(round(num(chapters_value, DEFAULTS["chaptersPerUnit"]))))

        range_start = int(round(num(data.get("rangeStart"), DEFAULTS["rangeStart"])))
        range_end = int(round(num(data.get("rangeEnd"), DEFAULTS["rangeEnd"])))
        self.range_start = max(1, range_start)
        self.range_end = max(self.range_start, range_end)

        self.levels, self.switch_level, self.profile_name = resolve_levels(
            self.profile, data.get("switchLevel")
        )

    @classmethod
    def from_mapping(cls, raw=None):
        return cls(raw)

    def as_controller_options(self):
        """交给 JS 控制器的选项（键名与 JS 侧 DEFAULTS 对齐）。"""
        profile_data, _ = resolve_profile(self.profile_name)
        options = {
            "levels": self.levels,
            "switchLevel": self.switch_level,
            "switchInterval": self.switch_interval,
            "randomInterval": self.random_interval,
            "range": self.range,
            "rangeStart": self.range_start,
            "rangeEnd": self.range_end,
            "chaptersPerUnit": self.chapters_per_unit,
            "loop": self.loop,
            "minIntervalMs": self.min_interval_ms,
            "maxConsecutiveErrors": self.max_consecutive_errors,
            "maxIdleTicks": self.max_idle_ticks,
            "clickMode": self.click_mode,
            "maxLayerMisses": self.max_layer_misses,
        }
        dismiss = profile_data.get("dismissDialog")
        options["dismissDialog"] = dict(dismiss) if isinstance(dismiss, dict) else None
        return options

    def level_names(self):
        return [level["name"] for level in self.levels]

    def summary(self):
        """一行式日志（GUI / 日志文件共用）。"""
        range_part = (
            f"范围 [{self.range_start}, {self.range_end}] 单元×{self.chapters_per_unit} 小节"
            if self.range else "范围 全量"
        )
        return (
            f"profile={self.profile_name} 层级={'→'.join(self.level_names())} "
            f"步长={self.switch_level} 间隔={self.switch_interval:g}分钟"
            f"{'(随机)' if self.random_interval else ''} {range_part} "
            f"循环={'开' if self.loop else '关'} 下限={self.min_interval_ms / 1000:g}s"
        )


def describe_scope(settings: "TimeBrushingSettings") -> str:
    """把 range 配置翻译成「刷哪几节」的可读文本（GUI 日志用）。

    术语统一：`rangeStart/rangeEnd` 是按 `chaptersPerUnit` 换算后的**最外层节点**序号，
    对 current profile 就是「微课」。日志里一律称「节」，避免用户对着
    `范围 [1, 2] 单元×16 小节` 这种表述自己做换算。
    """
    levels = settings.level_names()
    anchor = levels[0] if levels else "节点"
    if not settings.range:
        return f"全部 {anchor}（未限定范围）"
    total = settings.range_end - settings.range_start + 1
    if total == 1:
        return f"第 {settings.range_start} 节（共 1 节）"
    return f"第 {settings.range_start}–{settings.range_end} 节（共 {total} 节）"


# ---------------------------------------------------------------------------- 注入脚本构建

#: 页面内操作对象的全局变量名（后续 start/stop/status 脚本都指向它）
JS_VAR = "__unipusTimeBrushing"

#: 页面内控制器日志缓冲的全局变量名。
#: 背景（2026-09-20 实测）：控制器内部有大量诊断日志（启动归位、层级点击未变化、
#: 熔断禁用、已完成判定），但注入 payload 走 JSON，函数无法序列化 → onLog 一直是空实现，
#: 真机排查时这些日志全部丢失（「启动归位未生效」就是因此无法直接定位）。
#: 做法：注入时挂一个收集器，日志先囤在页面内，由 Python 侧轮询拉取。
JS_LOG_VAR = "__unipusTimeBrushingLogs"

#: 页面内日志缓冲上限（超出丢弃最旧的），防止长时间挂机把日志囤爆页面内存
JS_LOG_MAX = 200

# 脚本返回值的硬性要求（2026-09-17 真机实测踩到）：
#   Selenium 的 execute_script 把脚本当作**函数体**执行（等价于 new Function(src)），
#   因此只有脚本里出现显式 `return` 才能把值传回 Python。裸的 `(function(){...})();`
#   只是表达式语句，返回值恒为 undefined → Python 侧拿到 None。
#   本模块所有脚本因此统一写成 `return (function () { ... })();`。
#   对应的离线验证：tests/test_time_brushing.py 用 new Function(src)() 复刻该包装语义。


def _dumps(value):
    """紧凑 JSON（避免注入脚本被换行折断），并保持非 ASCII 原样。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_inject_script(controller_source=None, options=None, autostart=True, var_name=JS_VAR,
                        log_var_name=JS_LOG_VAR):
    """生成可交给 `driver.execute_script()` 的注入脚本。

    兼容性要点（依据分析报告 §3 第 4 项）：Selenium 会把脚本包进函数体执行，
    因此顶层 `var` 不会外泄到 window；控制器本身是 UMD，正常路径会把构造函数挂到
    `globalThis`。但若页面全局存在 `module`（webpack 站点有可能），UMD 会改走
    `module.exports` → 这里显式做兜底取回，避免出现「注入成功但构造函数为 undefined」。

    另：`onLog` 是函数，无法经 JSON payload 传递，故在页面内就地挂载收集器
    （见 `JS_LOG_VAR` 注释）；Python 侧用 `build_logs_script()` 轮询取回。
    """
    source = controller_source if controller_source is not None else load_controller_source()
    payload = _dumps(options if options is not None else TimeBrushingSettings().as_controller_options())
    autostart_js = (
        f"        instance.start();\n"
        if autostart else ""
    )
    return (
        "return (function () {\n"
        "    var __prevModule = (typeof module !== \"undefined\") ? module : undefined;\n"
        f"{source}\n"
        "    var Ctor = (typeof TimeBrushingController !== \"undefined\") ? TimeBrushingController\n"
        "        : (__prevModule && __prevModule.exports) ? __prevModule.exports : null;\n"
        "    if (!Ctor) { throw new Error(\"TimeBrushingController 注入失败：构造函数不可用\"); }\n"
        f"    var options = {payload};\n"
        # 收集器：把控制器内部日志囤到页面变量，供 Python 侧轮询取回（函数不能走 JSON）
        f"    window.{log_var_name} = [];\n"
        "    options.onLog = function (msg) {\n"
        f"        var box = window.{log_var_name};\n"
        "        if (!box) { return; }\n"
        "        box.push({ t: Date.now(), msg: String(msg) });\n"
        f"        if (box.length > {JS_LOG_MAX}) {{ box.shift(); }}\n"
        "    };\n"
        "    var instance;\n"
        "    try {\n"
        f"        instance = new Ctor(options);\n"
        "    } catch (e) {\n"
        "        throw new Error(\"刷时长控制器初始化失败：\" + (e && e.message ? e.message : e));\n"
        "    }\n"
        f"    window.{var_name} = instance;\n"
        f"{autostart_js}"
        "    return {\n"
        "        ok: true,\n"
        f"        exists: !!window.{var_name},\n"
        f"        running: !!(window.{var_name} && window.{var_name}.running),\n"
        f"        levels: options.levels.length,\n"
        "        switchLevel: options.switchLevel\n"
        "    };\n"
        "})();\n"
    )


def build_logs_script(var_name=JS_LOG_VAR):
    """读取并清空页面内的控制器日志缓冲。

    与 `build_status_script` 分离是刻意的：status 的返回结构被 `TimeBrushingSession.status()`
    与多处测试断言依赖，塞进 logs 会破坏契约。
    """
    return (
        "return (function () {\n"
        f"    var box = window.{var_name} || [];\n"
        f"    window.{var_name} = [];\n"
        "    return { logs: box };\n"
        "})();\n"
    )


def build_start_script(var_name=JS_VAR):
    """启动（或从暂停态恢复）挂机。"""
    return (
        "return (function () {\n"
        f"    var inst = window.{var_name};\n"
        "    if (!inst) { return { ok: false, reason: 'not-injected' }; }\n"
        "    var started = inst.start();\n"
        "    return { ok: true, started: !!started, running: !!inst.running };\n"
        "})();\n"
    )


def build_stop_script(finished=False, var_name=JS_VAR):
    """停止挂机；`finished=True` 表示正常刷完（会触发 onStop 回调语义）。"""
    return (
        "return (function () {\n"
        f"    var inst = window.{var_name};\n"
        "    if (!inst) { return { ok: true, existed: false }; }\n"
        f"    inst.stop({'true' if finished else 'false'});\n"
        f"    return {{ ok: true, existed: true, running: !!window.{var_name}.running }};\n"
        "})();\n"
    )


def build_status_script(var_name=JS_VAR):
    """读取页面内挂机状态（不存在的实例不算错误，交由 Python 侧判定）。"""
    return (
        "return (function () {\n"
        f"    var inst = window.{var_name};\n"
        "    if (!inst) { return { injected: false, running: false, finished: false, ticks: 0 }; }\n"
        "    return {\n"
        "        injected: true,\n"
        "        running: !!inst.running,\n"
        "        finished: !!inst.finished,\n"
        "        ticks: inst.tickCount || 0\n"
        "    };\n"
        "})();\n"
    )


def build_probe_script(profile=None, extra_selectors=None, extra_classes=None):
    """生成「现场校准」脚本：一次性返回各层候选选择器命中数与选中态类名命中数。

    用途：分析报告 §4.1 指出侧栏选中态类名未验证。把本脚本贴到浏览器控制台（或经
    execute_script 执行），即可确认哪套 selector / activeClass 真正生效，再据此更新
    `LEVEL_PROFILES` —— 不需要改控制器 JS。
    """
    profile_data, profile_name = resolve_profile(profile)
    groups = []
    for level in profile_data["levels"]:
        groups.append({
            "name": level["name"],
            "selectors": list(level.get("selectors", [])),
            "activeClasses": list(level.get("activeClasses", [])),
        })
    payload = _dumps({
        "profile": profile_name,
        "levels": groups,
        "extraSelectors": list(extra_selectors or []),
        "extraClasses": list(extra_classes or []),
    })
    return (
        "return (function () {\n"
        f"    var cfg = {payload};\n"
        "    function count(sel) { try { return document.querySelectorAll(sel).length; } catch (e) { return -1; } }\n"
        "    function classCount(cls) {\n"
        "        try {\n"
        "            return Array.prototype.filter.call(\n"
        "                document.querySelectorAll('*'),\n"
        "                function (el) { return el.classList && el.classList.contains(cls); }\n"
        "            ).length;\n"
        "        } catch (e) { return -1; }\n"
        "    }\n"
        "    var out = { profile: cfg.profile, href: location.href, levels: [] };\n"
        "    cfg.levels.forEach(function (lv) {\n"
        "        var selectors = {};\n"
        "        lv.selectors.forEach(function (s) { selectors[s] = count(s); });\n"
        "        var classes = {};\n"
        "        lv.activeClasses.forEach(function (c) { classes[c] = classCount(c); });\n"
        "        out.levels.push({ name: lv.name, selectors: selectors, activeClasses: classes });\n"
        "    });\n"
        "    var extra = {};\n"
        "    cfg.extraSelectors.forEach(function (s) { extra[s] = count(s); });\n"
        "    out.extraSelectors = extra;\n"
        "    var extraCls = {};\n"
        "    cfg.extraClasses.forEach(function (c) { extraCls[c] = classCount(c); });\n"
        "    out.extraClasses = extraCls;\n"
        "    return out;\n"
        "})();\n"
    )


# ---------------------------------------------------------------------------- 配置块组装

#: 配置编辑器暴露的字段（键名即 config.json 中 `time_brushing` 的子键）
EDITOR_FIELDS = (
    "enabled",
    "profile",
    "switchLevel",
    "switchInterval",
    "randomInterval",
    "range",
    "rangeStart",
    "rangeEnd",
    "chaptersPerUnit",
    "loop",
    "minIntervalMs",
    "clickMode",
    "maxLayerMisses",
)


def build_config_block(editor_values=None, previous=None):
    """把配置编辑器收集到的原始值组装成 config.json 的 `time_brushing` 块。

    两点刻意设计：
      1. **不丢配置**：配置编辑器保存时是「整份覆盖 config.json」，因此未被 UI 暴露的
         子键（`previous` 里存在的）必须原样保留，否则用户手写的键会被静默抹掉；
      2. **单一事实来源**：数值/布尔归一化统一走 `TimeBrushingSettings`，
         保存进文件的即是运行时实际生效的值，避免「文件里写 99、运行时夹到 4」这类表里不一。
    """
    block = dict(previous) if isinstance(previous, dict) else {}
    incoming = editor_values if isinstance(editor_values, dict) else {}
    for key in EDITOR_FIELDS:
        if key in incoming:
            block[key] = incoming[key]

    settings = TimeBrushingSettings(block)
    block.update({
        "enabled": settings.enabled,
        "profile": settings.profile_name,
        "switchLevel": settings.switch_level,
        "switchInterval": settings.switch_interval,
        "randomInterval": settings.random_interval,
        "range": settings.range,
        "rangeStart": settings.range_start,
        "rangeEnd": settings.range_end,
        "chaptersPerUnit": settings.chapters_per_unit,
        "loop": settings.loop,
        "minIntervalMs": settings.min_interval_ms,
        "clickMode": settings.click_mode,
        "maxLayerMisses": settings.max_layer_misses,
    })
    return block


# ---------------------------------------------------------------------------- 运行层
#
# 线程约束（重要）：Selenium driver 不是线程安全的。项目既有做法是「同一时刻只有一个
# 工作线程碰 driver」（答题走 `_run_auto_task` 线程）。刷时长同样只允许一个看护线程，
# 且必须与答题互斥 —— 由 `ModeGuard` 显式登记，而不是靠约定。

#: 会话状态取值
STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_FINISHED = "finished"
STATE_LOST = "lost"


class TimeBrushingError(RuntimeError):
    """刷时长模块的可预期故障（注入失败 / 驱动异常 / 返回值异常），带上下文供 GUI 展示。"""


class ModeGuard:
    """长任务模式互斥门闩：同一时刻只允许一个模式持有。

    背景（分析报告 §4.3）：刷题与刷时长都要点击顶部 Tab，必须显式互斥，否则会互相抢 DOM。
    答题侧只需在开跑前 `acquire("solving")`、结束时 `release("solving")`。
    """

    MODES = ("brushing", "solving")

    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None

    def acquire(self, mode) -> bool:
        """登记持有；同一模式重复 acquire 视为成功（幂等）。"""
        if mode not in self.MODES:
            raise ValueError(f"未知模式：{mode}（可选 {self.MODES}）")
        with self._lock:
            if self._owner is None or self._owner == mode:
                self._owner = mode
                return True
            return False

    def release(self, mode) -> bool:
        with self._lock:
            if self._owner == mode:
                self._owner = None
                return True
            return False

    @property
    def owner(self):
        with self._lock:
            return self._owner

    def blocked_by(self, mode):
        """返回「正在阻止 mode 的模式名」，无阻塞时返回 None。"""
        with self._lock:
            if self._owner is not None and self._owner != mode:
                return self._owner
            return None


class TimeBrushingSession:
    """单次刷时长会话：把控制器注入当前页面，并按需启停 / 读状态。

    与驱动解耦：只要求 `driver.execute_script(script)` 可用（测试用假 driver 即可覆盖）。
    """

    def __init__(self, driver, settings=None, log=None, var_name=JS_VAR,
                 source_loader=load_controller_source, log_var_name=JS_LOG_VAR):
        self.driver = driver
        self.settings = settings if isinstance(settings, TimeBrushingSettings) else \
            TimeBrushingSettings(settings)
        self.log = log
        self.var_name = var_name
        self.log_var_name = log_var_name
        self._source_loader = source_loader
        self._injected = False
        self._finished = False
        self._paused = False
        self.last_result = None

    # ---------------------------------------------------------------- 内部

    def _log(self, message):
        if callable(self.log):
            self.log(message)
        else:
            print(message)

    def _execute(self, script, action):
        try:
            result = self.driver.execute_script(script)
        except Exception as exc:  # noqa: BLE001 - 需要连原始异常一起上报
            raise TimeBrushingError(f"{action}失败：{type(exc).__name__}: {exc}") from exc
        if result is None:
            return {}
        if isinstance(result, dict):
            return result
        return {"value": result}

    def _source(self):
        return self._source_loader()

    # ---------------------------------------------------------------- 对外

    @property
    def injected(self) -> bool:
        return self._injected

    @property
    def finished(self) -> bool:
        return self._finished

    def inject(self, autostart=True):
        """注入控制器（可重复调用，用于页面整页跳转后的重注入）。"""
        options = self.settings.as_controller_options()
        script = build_inject_script(
            controller_source=self._source(),
            options=options,
            autostart=autostart,
            var_name=self.var_name,
            log_var_name=self.log_var_name,
        )
        result = self._execute(script, "注入刷时长控制器")
        if not result.get("ok") or not result.get("exists"):
            raise TimeBrushingError(f"注入结果异常：{result}")
        self._injected = True
        self._finished = False
        self._paused = not autostart
        self.last_result = result
        self._log(
            f"刷时长控制器已注入（{result.get('levels')} 层，步长 {result.get('switchLevel')}，"
            f"{'已自动启动' if autostart else '待启动'}）"
        )
        return result

    def status(self):
        """读取页面内状态；页面跳转导致实例丢失时返回 injected=False（非异常）。"""
        result = self._execute(build_status_script(self.var_name), "读取挂机状态")
        self._injected = bool(result.get("injected"))
        if self._injected:
            self._finished = bool(result.get("finished"))
        self.last_result = result
        return result

    def drain_logs(self):
        """拉取并清空页面内控制器日志，返回 [{"t": ts, "msg": str}, ...]。

        读日志失败不应影响挂机主流程（页面跳转、控制器丢失等都可能让脚本抛错），
        因此这里吞掉 `TimeBrushingError` 并返回空列表。
        """
        try:
            result = self._execute(build_logs_script(self.log_var_name), "读取控制器日志")
        except TimeBrushingError:
            return []
        logs = result.get("logs")
        return logs if isinstance(logs, list) else []

    def ensure_injected(self, autostart=True) -> bool:
        """确认控制器存在；丢失则重新注入。返回是否是本次新注入的。"""
        status = self.status()
        if status.get("injected"):
            return False
        self._log("页面内未发现刷时长控制器（可能已整页跳转），重新注入")
        self.inject(autostart=autostart)
        return True

    def start(self) -> bool:
        """启动或从暂停态恢复。"""
        self.ensure_injected(autostart=False)
        result = self._execute(build_start_script(self.var_name), "启动挂机")
        if not result.get("ok"):
            raise TimeBrushingError(f"启动失败：{result.get('reason') or result}")
        running = bool(result.get("running"))
        self._paused = not running
        if not running:
            self._log("控制器未进入运行态（可能已在运行或已结束）")
        return running

    def stop(self, finished=False) -> bool:
        """停止挂机；`finished=True` 表示正常刷完（页面内会触发 onStop(true)）。"""
        result = self._execute(build_stop_script(finished=finished, var_name=self.var_name), "停止挂机")
        self._paused = not finished
        self._finished = bool(finished)
        self.last_result = result
        return True

    def pause(self) -> bool:
        """暂停（= 停止但保留已注入实例，可 resume）。"""
        self.stop(finished=False)
        self._log("挂机已暂停，可随时恢复")
        return True

    def resume(self) -> bool:
        return self.start()

    def reset(self) -> bool:
        """丢弃当前实例（例如换课程后），下次 start 会重新注入。"""
        try:
            self.stop(finished=False)
        except TimeBrushingError as exc:
            self._log(f"停止旧实例时出错（忽略）：{exc}")
        self._injected = False
        self._finished = False
        self._paused = False
        return True

    def state(self) -> str:
        """推导当前会话状态（不发起新的页面查询，避免额外开销）。"""
        if not self._injected:
            return STATE_LOST
        if self._finished:
            return STATE_FINISHED
        if self._paused:
            return STATE_PAUSED
        return STATE_RUNNING


class TimeBrushingRunner:
    """刷时长线程宿主：负责启动 / 看护 / 停止，并与答题模式互斥。

    看护循环只做两件事：① 控制器丢失（整页跳转）→ 重新注入并启动；
    ② 控制器报告 finished → 结束线程。真正的切换节奏由页面内控制器自己掌握，
    Python 侧不参与定时，避免「双层定时器」互相干扰。
    """

    def __init__(self, driver, settings=None, log=None, guard=None,
                 poll_interval=15.0, session=None):
        """看护间隔默认 15s。

        该间隔同时决定「控制器日志透传到 Python/GUI 的延迟」—— 每次看护才 drain 一次，
        间隔过大（原 45s）会让界面上看到的进度明显滞后于实际切换节奏。
        15s 下每轮 2 次 execute_script（status + logs），开销可忽略。
        """
        self.log = log
        self.guard = guard if guard is not None else ModeGuard()
        self.poll_interval = max(0.01, float(poll_interval))
        self.session = session if session is not None else TimeBrushingSession(driver, settings, log)
        self.state = STATE_IDLE
        self.last_error = None
        self.polls = 0
        self._error_count = 0
        self._thread = None
        self._stop_event = threading.Event()
        self._guard_held = False

    # ---------------------------------------------------------------- 内部

    def _log(self, message):
        if callable(self.log):
            self.log(message)
        else:
            print(message)

    def _release_guard(self):
        if self._guard_held:
            self.guard.release("brushing")
            self._guard_held = False

    def _drain_controller_logs(self):
        """把页面内控制器的内部日志转发到 Python 日志。

        必要性（2026-09-20 实测教训）：控制器的「启动归位 / 层级点击未变化 / 熔断禁用 /
        已到范围末端」等判断全在页面内，若不透传，真机排查时这些信息完全不可见。
        日志通道本身不应影响主流程，因此读取失败只记一笔。
        """
        try:
            entries = self.session.drain_logs()
        except Exception as exc:  # noqa: BLE001 - 日志通道失败不阻断挂机
            self._log(f"读取控制器日志失败（忽略）：{type(exc).__name__}: {exc}")
            return
        for entry in entries:
            msg = entry.get("msg") if isinstance(entry, dict) else entry
            if msg:
                # 前缀用「页面」而非「controller」：日志面板面向中文用户，
                # 一眼看出这条来自页面内控制器（进度 / 归位 / 熔断）。
                self._log(f"[页面] {msg}")

    def _loop(self):
        try:
            while not self._stop_event.wait(self.poll_interval):
                try:
                    state = self.tick_once()
                except TimeBrushingError as exc:
                    self.last_error = exc
                    self._error_count += 1
                    limit = self.session.settings.max_consecutive_errors
                    self._log(f"看护异常（{self._error_count}/{limit}）：{exc}")
                    if self._error_count >= limit:
                        self.state = STATE_LOST
                        self._log("连续看护异常达上限，已停止挂机看护")
                        break
                    continue
                self._error_count = 0
                if state == STATE_FINISHED:
                    break
        finally:
            self._release_guard()

    # ---------------------------------------------------------------- 对外

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """启动挂机：校验开关与互斥 → 首次注入 → 起看护线程。"""
        if self.running:
            self._log("挂机已在运行中")
            return False
        settings = self.session.settings
        if not settings.enabled:
            self._log("配置中未启用刷时长（time_brushing.enabled=false），未启动")
            return False
        blocked = self.guard.blocked_by("brushing")
        if blocked is not None:
            self._log(f"当前已处于「{blocked}」模式，刷时长与答题互斥，未启动")
            return False
        if not self.guard.acquire("brushing"):
            self._log("未能取得刷时长模式占用，未启动")
            return False
        self._guard_held = True

        self._log(f"刷时长配置：{settings.summary()}")
        self._log(f"本次范围：{describe_scope(settings)}；层级 {' → '.join(settings.level_names())}"
                  f"（每次成功切换都会输出当前节次）")
        try:
            self.session.inject(autostart=True)
        except TimeBrushingError as exc:
            self.last_error = exc
            self._log(f"启动失败：{exc}")
            self._release_guard()
            self.state = STATE_IDLE
            return False

        self.state = STATE_RUNNING
        self._stop_event.clear()
        self._error_count = 0
        self._thread = threading.Thread(target=self._loop, name="time-brushing-watchdog", daemon=True)
        self._thread.start()
        # 注入时已 autostart，启动阶段（尤其是 range 归位）的日志要立刻取回，不能等第一次看护
        self._drain_controller_logs()
        self._log(f"刷时长已启动，每 {self.poll_interval:g}s 看护一次（切换节奏由页面内控制器掌握）")
        return True

    def tick_once(self) -> str:
        """执行一次看护（可单独调用，便于离线测试与手动诊断）。"""
        self.polls += 1
        status = self.session.status()
        self._drain_controller_logs()
        if not status.get("injected"):
            self._log("控制器不在页面内，重新注入")
            self.session.inject(autostart=True)
            self.state = STATE_RUNNING
        elif status.get("finished"):
            self.state = STATE_FINISHED
            self._log("控制器报告已完成（未开启循环或已到范围末端），看护结束")
        elif status.get("running"):
            self.state = STATE_RUNNING
        else:
            self.state = STATE_PAUSED
        return self.state

    def stop(self, finished=False, timeout=10.0) -> bool:
        """停止挂机：先让页面内控制器停下，再收线程、释放模式占用。"""
        if not self.running and self.state in (STATE_IDLE,):
            return False
        # 收尾前先取回残留日志（例如「已到范围末端且未开启循环，任务结束」）
        self._drain_controller_logs()
        try:
            self.session.stop(finished=finished)
        except TimeBrushingError as exc:
            self.last_error = exc
            self._log(f"停止页面内控制器失败（继续收线程）：{exc}")
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                self._log(f"看护线程在 {timeout:g}s 内未退出（daemon，不影响退出）")
        self._thread = None
        self.state = STATE_FINISHED if finished else STATE_IDLE
        self._release_guard()
        self._log("刷时长已停止" + ("（正常刷完）" if finished else ""))
        return True

    def pause(self) -> bool:
        if not self.session.injected:
            return False
        self.session.pause()
        self.state = STATE_PAUSED
        return True

    def resume(self) -> bool:
        if not self.session.injected:
            self._log("尚未注入控制器，无法恢复；请重新启动")
            return False
        self.session.resume()
        self.state = STATE_RUNNING
        return True


# ---------------------------------------------------------------------------- 现场校准（P0 前置验证的执行入口）

def run_probe(driver, profile=None, extra_selectors=None, extra_classes=None):
    """在**当前页面**执行现场校准脚本，返回各层级候选选择器与选中态类名的命中数。

    用途（对应分析报告 §4.1 与 §6.3 的 P0 前置验证）：
    把浏览器停在课程页后执行本函数，即可一次性确认
      ① 侧栏 `div[data-role="section"/"micro"]` 的真实结构与选中态类名；
      ② 一级/二级 Tab 的候选选择器是否仍然命中；
      ③ 顺带探测任意自定义选择器/类名（extra_selectors / extra_classes）。

    返回结构（JSON 可序列化）：
      {"profile": "...", "href": "...", "levels": [{"name","selectors":{sel:count},
       "activeClasses":{cls:count}}, ...], "extraSelectors": {...}, "extraClasses": {...}}
      其中计数为 -1 表示该选择器语法非法（`querySelectorAll` 抛错）。
    """
    script = build_probe_script(profile, extra_selectors, extra_classes)
    try:
        result = driver.execute_script(script)
    except Exception as exc:  # noqa: BLE001 - 需要带上原始异常信息
        raise TimeBrushingError(f"现场校准脚本执行失败：{type(exc).__name__}: {exc}") from exc
    if not isinstance(result, dict):
        raise TimeBrushingError(f"现场校准返回异常（期望 dict）：{result!r}")
    return result


def format_probe_result(result):
    """把 `run_probe()` 的结果整理成可读文本（写日志或落盘，避免只丢一坨 JSON）。"""
    if not isinstance(result, dict):
        return f"校准结果格式异常：{result!r}"
    lines = [f"现场校准 profile={result.get('profile')} url={result.get('href')}"]
    for level in result.get("levels") or []:
        selectors = level.get("selectors") or {}
        classes = level.get("activeClasses") or {}
        hit = [f"{sel} → {count}" for sel, count in selectors.items()]
        cls = [f"{name} → {count}" for name, count in classes.items()]
        lines.append(f"  [{level.get('name')}] 选择器: " + ("；".join(hit) or "无"))
        lines.append(f"  [{level.get('name')}] 选中态类名: " + ("；".join(cls) or "无"))
    for key, title in (("extraSelectors", "附加选择器"), ("extraClasses", "附加类名")):
        extra = result.get(key) or {}
        if extra:
            lines.append(f"  {title}: " + "；".join(f"{k} → {v}" for k, v in extra.items()))
    return "\n".join(lines)


# ---------------------------------------------------------------------------- 侧栏选中态普查（定稿类名的决定性证据）

#: 侧栏层级节点（当前站点由 23 份落盘确认）
SIDEBAR_ROLES = ("unit", "section", "micro")
#: 页头「当前激活」标记
ACTIVE_TASK_SELECTOR = ".pc-header-tasks-row > .pc-task[class*='activity']"
ACTIVE_TAB_SELECTOR = ".pc-header-tabs-container .pc-tab-row > .tab[class*='activity']"
#: 侧栏节点名字（形如 <span class="pc-menu-node-name">Reading</span>）
SIDEBAR_NAME_SELECTOR = ".pc-menu-node-name"


def build_sidebar_census_script(roles=None, active_task_selector=ACTIVE_TASK_SELECTOR,
                                active_tab_selector=ACTIVE_TAB_SELECTOR,
                                name_selector=SIDEBAR_NAME_SELECTOR):
    """生成「侧栏选中态普查」脚本。

    为什么需要它（分析报告 §4.1）：侧栏节点在 23 份落盘里恒为 `pc-menu-default`，
    从来没有出现过任何 active 类名，所以只统计类名分布不足以定稿。本脚本同时做三件事：

      1. 统计各 role 节点的**类名分布**，并单独列出「只出现 1 次」的类名
         （当前选中项通常就是这一类）；
      2. 读出页头**当前激活**的一级 Tab / 二级 Task 标题（这两个类名已 23/23 验证）；
      3. 拿标题去侧栏按名字**回查同名节点**，直接给出该节点的 `data-role` 与完整 class
         —— 这才是「选中态类名 + 所属元素」的确定性证据。

    只读脚本，不点击、不改页面。
    """
    payload = _dumps({
        "roles": list(roles or SIDEBAR_ROLES),
        "activeTask": active_task_selector,
        "activeTab": active_tab_selector,
        "nameSelector": name_selector,
    })
    return (
        "return (function () {\n"
        f"    var cfg = {payload};\n"
        "    function cls(node) { return (node && node.className) || ''; }\n"
        "    function text(node) { return node ? (node.textContent || '').trim().slice(0, 80) : null; }\n"
        "    var out = { url: location.href, title: document.title, roles: {}, active: {}, matches: [] };\n"
        "    cfg.roles.forEach(function (role) {\n"
        "        var nodes = document.querySelectorAll('div[data-role=\"' + role + '\"]');\n"
        "        var classes = {};\n"
        "        var samples = [];\n"
        "        Array.prototype.forEach.call(nodes, function (node) {\n"
        "            cls(node).split(/\\s+/).forEach(function (c) { if (c) classes[c] = (classes[c] || 0) + 1; });\n"
        "            if (samples.length < 3) samples.push({ text: text(node), cls: cls(node) });\n"
        "        });\n"
        "        var unique = [];\n"
        "        Object.keys(classes).forEach(function (k) { if (classes[k] === 1) unique.push(k); });\n"
        "        out.roles[role] = { count: nodes.length, classes: classes, onceOnly: unique, samples: samples };\n"
        "    });\n"
        "    out.active.task = text(document.querySelector(cfg.activeTask));\n"
        "    out.active.tab = text(document.querySelector(cfg.activeTab));\n"
        "    var names = document.querySelectorAll(cfg.nameSelector);\n"
        "    Array.prototype.forEach.call(names, function (span) {\n"
        "        var name = text(span);\n"
        "        if (!name) { return; }\n"
        "        if (name !== out.active.task && name !== out.active.tab) { return; }\n"
        "        var node = span.closest ? span.closest('div[data-role]') : null;\n"
        "        if (!node) {\n"
        "            var parent = span.parentElement;\n"
        "            out.matches.push({ name: name, role: null, cls: cls(parent), viaSpanParent: true });\n"
        "            return;\n"
        "        }\n"
        "        out.matches.push({ name: name, role: node.getAttribute('data-role'), cls: cls(node), viaSpanParent: false });\n"
        "    });\n"
        "    return out;\n"
        "})();\n"
    )


def run_sidebar_census(driver, **kwargs):
    """在当前页面执行侧栏普查，返回结构化结果（只读，不点击）。"""
    script = build_sidebar_census_script(**kwargs)
    try:
        result = driver.execute_script(script)
    except Exception as exc:  # noqa: BLE001
        raise TimeBrushingError(f"侧栏普查脚本执行失败：{type(exc).__name__}: {exc}") from exc
    if not isinstance(result, dict):
        raise TimeBrushingError(f"侧栏普查返回异常（期望 dict）：{result!r}")
    return result


def format_census_result(result):
    """把普查结果整理成可读文本（定稿类名时直接读这段）。"""
    if not isinstance(result, dict):
        return f"普查结果格式异常：{result!r}"
    lines = [f"页面: {result.get('title')} | {result.get('url')}"]
    active = result.get("active") or {}
    lines.append(f"当前激活: 二级Task={active.get('task')!r} 一级Tab={active.get('tab')!r}")
    for role, info in (result.get("roles") or {}).items():
        lines.append(
            f"  [{role}] 节点数={info.get('count')} 仅在 1 个节点出现的类名={info.get('onceOnly')}"
        )
        classes = info.get("classes") or {}
        top = sorted(classes.items(), key=lambda kv: -kv[1])[:6]
        lines.append("      类名分布: " + "；".join(f"{k}×{v}" for k, v in top))
        for sample in info.get("samples") or []:
            lines.append(f"      样例: {sample.get('cls')!r} text={sample.get('text')!r}")
    matches = result.get("matches") or []
    if matches:
        for match in matches:
            lines.append(
                f"  ★ 同名匹配: name={match.get('name')!r} role={match.get('role')} cls={match.get('cls')!r}"
            )
    else:
        lines.append("  ★ 同名匹配: 无（当前激活项未在侧栏找到同名节点，需人工确认）")
    return "\n".join(lines)
