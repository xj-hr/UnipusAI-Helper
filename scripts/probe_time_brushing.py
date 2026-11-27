# -*- coding: utf-8 -*-
"""刷时长真机校准 / 首次挂机验证（一次性诊断脚本，独立于 GUI）。

用途：把分析报告 §6.3 的 P0 前置验证与实际挂机各跑一遍，产出可归档的证据。
不修改 config.json（挂机节奏以内存参数覆盖），不改动 AISolver。

用法：
    <venv python> scripts/probe_time_brushing.py                      # 只探测
    <venv python> scripts/probe_time_brushing.py --brush              # 探测 + 短间隔挂机观察
    <venv python> scripts/probe_time_brushing.py --url "<课程内容页URL>"  # 覆盖默认课程页

结果落盘：logs/time_brushing_live_<时间戳>.json 与同名 .txt（同时打印到标准输出）。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

#: 本脚本位于 scripts/ 下，项目根目录取上两级，保证 config.json / logs/ 路径不变
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 导入顺序：先加载本模块（其首行 import AudioRecognizer 先拉起 torch），再碰 Qt/Selenium
import UnipusAI_Helper as m  # noqa: E402
import time_brushing as tb  # noqa: E402

#: 课程内容页需由使用者用 --url 传入：仓库是公开的，具体 cid/课程 ID 不入库
DEFAULT_COURSE_URL = ""

#: 页面快照脚本：只读，返回当前激活的页头 tab/task 与侧栏里带 active 字样的节点
#: 注意：Selenium 把脚本当函数体执行，必须显式 return 才能拿到返回值（真机实测踩到）
SNAPSHOT_JS = """
return (function () {
    function text(node) { return node ? (node.textContent || '').trim().slice(0, 60) : null; }
    var out = {
        url: location.href,
        headerTask: text(document.querySelector(".pc-header-tasks-row > .pc-task[class*='activity']")),
        headerTab: text(document.querySelector(".pc-header-tabs-container .pc-tab-row > .tab[class*='activity']")),
        tasks: document.querySelectorAll(".pc-header-tasks-row > .pc-task").length,
        sections: document.querySelectorAll('div[data-role="section"]').length,
        micros: document.querySelectorAll('div[data-role="micro"]').length,
        activeLike: []
    };
    Array.prototype.forEach.call(document.querySelectorAll('div[data-role]'), function (node) {
        var cls = node.className || '';
        if (/active|selected|current/i.test(cls)) {
            out.activeLike.push({ role: node.getAttribute('data-role'), cls: cls, text: text(node) });
        }
    });
    out.activeLike = out.activeLike.slice(0, 8);
    return out;
})();
"""


#: 安装「点击记录器」：捕获阶段监听，连 el.click() 这类程序化点击也能抓到，
#: 用于回答「控制器到底点了哪个元素」。只记录、不阻断（不调用 preventDefault）。
CLICK_TAP_JS = """
return (function () {
    if (window.__tbTapInstalled) { return { installed: false, already: true }; }
    window.__tbTapInstalled = true;
    window.__tbClicks = [];
    function desc(el) {
        if (!el || !el.tagName) { return null; }
        return {
            tag: el.tagName,
            cls: (typeof el.className === "string" ? el.className : ""),
            text: (el.textContent || "").trim().slice(0, 40)
        };
    }
    document.addEventListener("click", function (event) {
        var el = event.target;
        var node = (el && el.closest) ? el.closest("div[data-role], .tab, .pc-task") : null;
        window.__tbClicks.push({
            t: Date.now(),
            trusted: !!event.isTrusted,
            target: desc(el),
            node: desc(node),
            role: node && node.getAttribute ? node.getAttribute("data-role") : null
        });
        if (window.__tbClicks.length > 200) { window.__tbClicks.shift(); }
    }, true);
    return { installed: true };
})();
"""

#: 读取并清空点击记录（每次轮询取一次，便于把点击归到相邻采样区间）
READ_CLICKS_JS = """
return (function () {
    var list = window.__tbClicks || [];
    window.__tbClicks = [];
    return { clicks: list };
})();
"""

#: 逐层快照：对 profile 的每一层给出 count / activeIndex / activeText，
#: 另附侧栏选中项与主内容区文本，用于区分「点击无效」与「视觉未更新」
LAYER_SNAPSHOT_TEMPLATE = """
return (function () {
    var cfg = %s;
    function txt(node, n) { return node ? (node.textContent || "").trim().replace(/\\s+/g, " ").slice(0, n || 40) : null; }
    var out = { url: location.href, ts: Date.now(), layers: {}, sidebarActive: null, contentMark: null };
    cfg.forEach(function (lv) {
        var items = document.querySelectorAll(lv.selector);
        var idx = -1, activeText = null, texts = [];
        Array.prototype.forEach.call(items, function (node, i) {
            var value = txt(node);
            if (texts.length < 12) { texts.push(value); }
            if (idx < 0 && node.classList && node.classList.contains(lv.activeClass)) {
                idx = i; activeText = value;
            }
        });
        out.layers[lv.name] = { count: items.length, activeIndex: idx, activeText: activeText, texts: texts };
    });
    var act = document.querySelector("div[data-role].pc-menu-activity");
    if (act) { out.sidebarActive = { role: act.getAttribute("data-role"), text: txt(act) }; }
    var main = document.querySelector("#main-content");
    if (main) { out.contentMark = txt(main, 80); }
    return out;
})();
"""


def build_layer_snapshot_script(levels):
    """按 profile 的层级生成逐层快照脚本（选择器与选中态类名都来自配置）。"""
    payload = json.dumps(
        [{"name": lv["name"], "selector": lv["selector"], "activeClass": lv["activeClass"]} for lv in levels],
        ensure_ascii=False,
    )
    return LAYER_SNAPSHOT_TEMPLATE % payload


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def dump(out_dir, stamp, payload, text):
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, f"time_brushing_live_{stamp}.json")
    txt_path = os.path.join(out_dir, f"time_brushing_live_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    log(f"结果已落盘：{json_path}")
    log(f"可读报告：{txt_path}")


def wait_for(driver, predicate, timeout, interval=3.0, label=""):
    """轮询等待谓词成立（用户手动操作也能被捕获），返回是否成立。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except Exception as exc:  # noqa: BLE001
            log(f"轮询异常（忽略）：{type(exc).__name__}: {exc}")
        time.sleep(interval)
    log(f"等待超时（{timeout:g}s）：{label}")
    return False


def snapshot(driver):
    try:
        return driver.execute_script(SNAPSHOT_JS) or {}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def read_token_meta(driver):
    """回读页面内 localStorage.__token 的过期时间（判断站点是否下发了新 token）。"""
    script = """
    return (function () {
        try {
            var raw = window.localStorage.getItem("__token");
            if (!raw) { return { present: false }; }
            var obj = JSON.parse(raw);
            var info = obj && obj.tokenInfo ? obj.tokenInfo : obj;
            return {
                present: true,
                length: raw.length,
                keys: Object.keys(obj || {}),
                jwtExpire: info && info.jwtExpire ? info.jwtExpire : null,
                rtExpire: info && info.rtExpire ? info.rtExpire : null
            };
        } catch (e) { return { present: false, error: String(e) }; }
    })();
    """
    try:
        return driver.execute_script(script) or {}
    except Exception as exc:  # noqa: BLE001
        return {"present": False, "error": f"{type(exc).__name__}: {exc}"}


def _click_layer(click):
    """把一次点击归到 profile 的层级名上。"""
    role = click.get("role")
    if role:
        return role
    cls = click.get("nodeCls") or ""
    if "pc-task" in cls:
        return "task"
    if "tab" in cls:
        return "activity"
    return "unknown"


def summarise_ticks(samples, clicks):
    """对比相邻 tick 的各层 active 文本，定位「已点击但未更新」的层级。

    判定思路：
      · 以控制器 ticks 递增为界，把相邻两个采样点作为「tick 前 / tick 后」；
      · 逐层比较 (activeIndex, activeText)：变了 = 该层推进生效；
      · 把点击按层级归类，得到「点击次数」；点击次数 > 0 而从未变化的层级即嫌疑层；
      · 若同一元素被反复点击，说明该层 activeIndex 未命中（点击落在当前项或无效元素）。
    """
    lines = []
    transitions = []
    prev = None
    for sample in samples:
        if prev is None:
            prev = sample
            continue
        if (sample.get("ticks") or 0) > (prev.get("ticks") or 0):
            transitions.append((prev, sample))
        prev = sample

    layer_names = sorted({name for sample in samples for name in (sample.get("layers") or {})})
    changed_by_layer = {name: 0 for name in layer_names}
    for before, after in transitions:
        for name in layer_names:
            b = (before.get("layers") or {}).get(name) or {}
            a = (after.get("layers") or {}).get(name) or {}
            if (b.get("activeIndex"), b.get("activeText")) != (a.get("activeIndex"), a.get("activeText")):
                changed_by_layer[name] += 1

    click_by_layer = {name: 0 for name in layer_names}
    click_targets = {}
    for click in clicks:
        layer = _click_layer(click)
        click_by_layer[layer] = click_by_layer.get(layer, 0) + 1
        key = f"{layer}|{click.get('node')!r}|{click.get('nodeCls')!r}"
        click_targets[key] = click_targets.get(key, 0) + 1

    lines.append(f"采样点 {len(samples)} 个，观测到 tick 递增 {len(transitions)} 次，记录点击 {len(clicks)} 次")
    lines.append("层级 | 点击次数 | 相邻 tick 中 active 变化次数 | 判定")
    suspects = []
    for name in layer_names:
        clicks_n = click_by_layer.get(name, 0)
        changed_n = changed_by_layer.get(name, 0)
        if clicks_n and not changed_n:
            verdict = "★ 已点击但 active 从未变化（点击未生效/落点错误）"
            suspects.append(name)
        elif clicks_n:
            verdict = "生效"
        else:
            verdict = "未被点击"
        lines.append(f"{name} | {clicks_n} | {changed_n} | {verdict}")
    if click_by_layer.get("unknown"):
        lines.append(f"未能归类的点击: {click_by_layer['unknown']} 次")

    if click_targets:
        lines.append("点击落点分布（层级 | 元素文本 | 类名 → 次数）：")
        for key, count in sorted(click_targets.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {key} → {count}")

    marks = []
    if len(samples) >= 2:
        first, last = samples[0], samples[-1]
        marks.append(("sidebarActive", (first.get("sidebarActive") or {}).get("text"),
                      (last.get("sidebarActive") or {}).get("text")))
        marks.append(("contentMark", first.get("contentMark"), last.get("contentMark")))
        for name in layer_names:
            marks.append((f"{name}.activeText",
                          ((first.get("layers") or {}).get(name) or {}).get("activeText"),
                          ((last.get("layers") or {}).get(name) or {}).get("activeText")))
    lines.append("首末快照对比（含侧栏选中与主内容区，用于判断视觉是否真的变化）：")
    for label, before, after in marks:
        same = "未变" if before == after else "已变"
        lines.append(f"  {label}: {same} | {before!r} → {after!r}")

    if suspects:
        lines.append("结论：嫌疑层级 = " + "、".join(suspects)
                     + "（该层被点击，但相邻 tick 的 activeIndex/activeText 从未变化）")
    elif clicks:
        lines.append("结论：所有被点击的层级都发生了 active 变化 → 点击生效")
    else:
        lines.append("结论：未记录到任何点击，需检查控制器是否真正推进（idle/熔断）")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_COURSE_URL,
                        help="课程内容页 URL（必填：浏览器打开任一课程页后复制地址栏）")
    parser.add_argument("--brush", action="store_true", help="探测后跑一次短间隔挂机观察")
    parser.add_argument("--brush-seconds", type=float, default=150.0, help="挂机观察时长（秒）")
    parser.add_argument("--poll-seconds", type=float, default=2.0,
                        help="逐层快照采样间隔（秒），需远小于切换间隔才能捕捉变化")
    parser.add_argument("--interval-minutes", type=float, default=0.5,
                        help="覆盖的切换间隔（分钟）；与 --use-config-interval 互斥")
    parser.add_argument("--use-config-interval", action="store_true",
                        help="让挂机节奏完全吃 config.json.time_brushing 的真实值（推荐用于验证配置链路）")
    parser.add_argument("--min-interval-seconds", type=float, default=15.0,
                        help="覆盖的最小间隔（秒）；--use-config-interval 时忽略")
    parser.add_argument("--login-wait", type=float, default=180.0, help="登录/人工验证等待上限（秒）")
    parser.add_argument("--page-wait", type=float, default=180.0, help="等待课程页出现侧栏的上限（秒）")
    args = parser.parse_args()
    if not args.url:
        print("缺少 --url：请先用浏览器打开任一课程页，把地址栏完整 URL 传给本脚本。")
        print('示例：python scripts/probe_time_brushing.py --url "https://ucontent.unipus.cn/...#/course-v2:..."')
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = os.path.join(BASE_DIR, "logs")
    report = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "course_url": args.url,
        "token_before": None,
        "login": None,
        "token_after_login": None,
        "census": None,
        "probe": None,
        "brush": None,
        "errors": [],
    }
    lines = []

    def add(text):
        lines.append(text)
        log(text)

    bot = None
    try:
        add("启动 Edge（临时 profile）...")
        bot = m.UCampusBot(os.path.join(BASE_DIR, "config.json"), skip_check=True)
        driver = bot.driver
        report["token_before"] = read_token_meta(driver)
        add(f"token（启动时）：{report['token_before']}")

        add("账号密码登录中（如弹出人机验证，请在浏览器窗口内手动完成）...")
        login_ok = bot._login()
        report["login"] = bool(login_ok)
        add(f"登录返回：{login_ok}")
        if not login_ok:
            add("⚠ 登录未确认为成功：若为站点人机验证所致，请在浏览器窗口内完成后重跑本脚本；"
                "此时后续探测结果不可用")
        if not login_ok:
            wait_for(driver, lambda: any(k in driver.current_url for k in ("home", "course", "space", "student")),
                     args.login_wait, label="等待人工完成登录")
        add(f"当前 URL：{driver.current_url}")
        report["token_after_login"] = read_token_meta(driver)
        add(f"token（登录后）：{report['token_after_login']}")

        add("打开课程内容页...")
        driver.get(args.url)
        time.sleep(3)

        def sidebar_ready():
            snap = snapshot(driver)
            return bool(snap.get("sections")) or bool(snap.get("headerTask"))

        page_ready = wait_for(driver, sidebar_ready, args.page_wait, label="等待课程内容页（侧栏/页头出现）")
        if not page_ready:
            add("页面未出现侧栏：请在浏览器中进入具体课程的任务页后重试（本脚本会在等待期内持续探测）")
        snap = snapshot(driver)
        add(f"页面快照：sections={snap.get('sections')} micros={snap.get('micros')} "
            f"tasks={snap.get('tasks')} headerTask={snap.get('headerTask')!r} headerTab={snap.get('headerTab')!r}")

        add("=== 侧栏选中态普查 ===")
        try:
            report["census"] = tb.run_sidebar_census(driver)
            census_text = tb.format_census_result(report["census"])
            for line in census_text.splitlines():
                add("  " + line)
        except tb.TimeBrushingError as exc:
            report["errors"].append(f"census: {exc}")
            add(f"普查失败：{exc}")

        add("=== 选择器探测（含候选 active 类名）===")
        try:
            report["probe"] = tb.run_probe(
                driver,
                extra_classes=[
                    "pc-menu-active", "pc-menu-current", "pc-menu-selected",
                    "pc-menu-check", "pc-menu-default",
                    "active", "selected", "current", "checked",
                ],
                extra_selectors=[
                    '.pc-slider-menu-section[class*="active"]',
                    '.pc-slider-menu-micro[class*="active"]',
                    'div[data-role="section"][class*="active"]',
                    'div[data-role="micro"][class*="active"]',
                    ".pc-menu-node-active", ".pc-menu-active",
                ],
            )
            probe_text = tb.format_probe_result(report["probe"])
            for line in probe_text.splitlines():
                add("  " + line)
        except tb.TimeBrushingError as exc:
            report["errors"].append(f"probe: {exc}")
            add(f"探测失败：{exc}")

        if args.brush and not page_ready:
            add("页面未就绪（侧栏/页头均未出现），跳过挂机验证：在登录页空转只会产出误导性的结论")
            report["brush"] = {"skipped": "page-not-ready", "url": snapshot(driver).get("url")}

        if args.brush and page_ready:
            add("=== 首次真机挂机验证（内存覆盖配置，不改 config.json）===")
            base = bot.config.time_brushing_settings()
            if args.use_config_interval:
                if args.interval_minutes != 0.5:
                    add("⚠ --interval-minutes 与 --use-config-interval 同时给出；忽略前者，"
                        "直接吃 config.json.time_brushing.switchInterval")
                # 节奏完全交给 config.json：仅保留 base 里的「打开开关 + 去掉 random」两项试验性覆盖
                override = {
                    "enabled": True,
                    "profile": base.profile_name,
                    "switchLevel": base.switch_level,
                    "switchInterval": base.switch_interval,        # ← 关键：直接吃 config.json
                    "minIntervalMs": base.min_interval_ms,        #   同上
                    "randomInterval": False,                      #   关随机便于观察
                    "range": base.range,
                    "rangeStart": base.range_start,
                    "rangeEnd": base.range_end,
                    "chaptersPerUnit": base.chapters_per_unit,
                    "loop": True,
                }
            else:
                override = {
                    "enabled": True,
                    "profile": base.profile_name,
                    "switchLevel": base.switch_level,
                    "switchInterval": args.interval_minutes,
                    "minIntervalMs": args.min_interval_seconds * 1000.0,
                    "randomInterval": False,
                    "range": base.range,
                    "rangeStart": base.range_start,
                    "rangeEnd": base.range_end,
                    "chaptersPerUnit": base.chapters_per_unit,
                    "loop": True,
                }
            settings = tb.TimeBrushingSettings(override)
            add(f"覆盖后配置：{settings.summary()}")

            # 安装点击记录器（在注入控制器之前），用于回答「控制器到底点了哪个元素」
            tap = driver.execute_script(CLICK_TAP_JS)
            add(f"点击记录器：{tap}")

            runner = tb.TimeBrushingRunner(
                driver, settings=settings, log=lambda msg: add("  [runner] " + str(msg)),
                guard=tb.ModeGuard(), poll_interval=10.0,
            )
            brush = {
                "settings": override,
                "started": False,
                "trace": [],
                "snapshots": [],
                "clicks": [],
                "poll_interval_s": args.poll_seconds,
            }
            report["brush"] = brush
            brush["started"] = runner.start()
            add(f"挂机启动：{brush['started']}")
            if brush["started"]:
                layer_js = build_layer_snapshot_script(settings.as_controller_options()["levels"])
                started = time.time()

                def sample(status):
                    snap = driver.execute_script(layer_js) or {}
                    clicks = (driver.execute_script(READ_CLICKS_JS) or {}).get("clicks", [])
                    return {
                        "t": round(time.time() - started, 1),
                        "running": bool(status.get("running")),
                        "finished": bool(status.get("finished")),
                        "ticks": status.get("ticks"),
                        "layers": {
                            name: {
                                "count": info.get("count"),
                                "activeIndex": info.get("activeIndex"),
                                "activeText": info.get("activeText"),
                            }
                            for name, info in (snap.get("layers") or {}).items()
                        },
                        "sidebarActive": snap.get("sidebarActive"),
                        "contentMark": snap.get("contentMark"),
                        "clicks": [
                            {"t": c.get("t"), "trusted": c.get("trusted"), "role": c.get("role"),
                             "node": (c.get("node") or {}).get("text"), "nodeCls": (c.get("node") or {}).get("cls")}
                            for c in clicks
                        ],
                    }

                brush["snapshots"].append(sample(runner.session.status()))
                while time.time() - started < args.brush_seconds:
                    time.sleep(max(0.5, args.poll_seconds))
                    entry = sample(runner.session.status())
                    brush["trace"].append(entry)
                    layer_desc = " | ".join(
                        f"{name}:{info.get('activeText')!r}@{info.get('activeIndex')}"
                        for name, info in entry["layers"].items()
                    )
                    add(f"  t={entry['t']}s ticks={entry['ticks']} {layer_desc}")
                    for click in entry["clicks"]:
                        brush["clicks"].append(click)
                        add(f"      ↳ 点击 role={click['role']} node={click['node']!r} cls={click['nodeCls']!r}"
                            f" trusted={click['trusted']}")
                brush["snapshots"].append(sample(runner.session.status()))
                runner.stop()
                add("挂机已停止")
                report["token_after_brush"] = read_token_meta(driver)
                add("=== 逐层变化对比（相邻 tick）===")
                for line in summarise_ticks(brush["snapshots"] + brush["trace"], brush["clicks"]):
                    add("  " + line)
    except Exception as exc:  # noqa: BLE001
        import traceback
        report["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        add(f"致命错误：{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        add(f"错误清单：{report['errors'] or '无'}")
        dump(logs_dir, stamp, report, "\n".join(lines) + "\n")
        if bot is not None and bot.driver is not None:
            try:
                bot.driver.quit()
                log("浏览器已关闭")
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
