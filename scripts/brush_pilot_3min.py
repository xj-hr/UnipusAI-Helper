# -*- coding: utf-8 -*-
"""刷时长真实实测（按页记录停留时长）。

用途：走真实链路（UCampusBot + TimeBrushingRunner + 页面内 JS 控制器），
配置直接读 config.json 的 time_brushing 段，逐页记录「进入时刻 / 离开时刻 / 实际停留时长」，
并把每个页面的点击与生效情况一并落盘，用于核对「配置的切换间隔是否真的生效」。

与 probe_time_brushing.py 的分工：
  · probe_time_brushing.py —— 只读普查 + 选择器校准 + 短间隔挂机观察（诊断用）
  · 本脚本 —— 按真实节奏跑完整实测，产出「每页停留时长」表格（验收用）

用法：
    <venv python> scripts/brush_pilot_3min.py                       # 读 config.json，跑到第一单元结束或触发上限
    <venv python> scripts/brush_pilot_3min.py --max-pages 8         # 只跑前 8 页（快速核对节奏）
    <venv python> scripts/brush_pilot_3min.py --max-minutes 60      # 总时长上限保护

结束条件（任一触发即停）：
    1. 控制器报告 finished（第一单元刷完，loop=false）
    2. 页面数达到 --max-pages
    3. 累计时长达到 --max-minutes
    4. 连续 N 次采样读不到控制器（页面异常）

结果落盘：logs/pilot_3min_<时间戳>.json 与同名 .txt
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

# 导入顺序硬性要求：先 UnipusAI_Helper（其首行 import AudioRecognizer 拉起 torch），再碰 Qt/Selenium
import UnipusAI_Helper as m  # noqa: E402
import time_brushing as tb  # noqa: E402

#: 课程内容页需由使用者用 --url 传入：仓库是公开的，具体 cid/课程 ID 不入库
DEFAULT_COURSE_URL = ""

#: 页面标识快照：读三层各自的 active 文本 + 页码 + 主内容区首段
#: 注意：Selenium 把脚本当函数体执行，必须显式 return
PAGE_STATE_TMPL = """
return (function () {
    var cfg = %s;
    function txt(node, n) { return node ? (node.textContent || "").trim().replace(/\\s+/g, " ").slice(0, n || 40) : null; }
    var out = { url: location.href, ts: Date.now(), layers: {}, contentMark: null };
    cfg.forEach(function (lv) {
        var items = document.querySelectorAll(lv.selector);
        var idx = -1, activeText = null;
        Array.prototype.forEach.call(items, function (node, i) {
            if (idx < 0 && node.classList && node.classList.contains(lv.activeClass)) {
                idx = i; activeText = txt(node);
            }
        });
        out.layers[lv.name] = { count: items.length, activeIndex: idx, activeText: activeText };
    });
    var main = document.querySelector("#main-content") || document.querySelector(".layout-material-container");
    if (main) { out.contentMark = txt(main, 60); }
    return out;
})();
"""

#: 点击记录器（与 probe 同源）：捕获阶段监听，程序化点击也能抓到
CLICK_TAP_JS = """
return (function () {
    if (window.__pilotTapInstalled) { return { installed: false, already: true }; }
    window.__pilotTapInstalled = true;
    window.__pilotClicks = [];
    function desc(el) {
        if (!el || !el.tagName) { return null; }
        return { tag: el.tagName, cls: (typeof el.className === "string" ? el.className : ""), text: (el.textContent || "").trim().slice(0, 30) };
    }
    document.addEventListener("click", function (event) {
        var el = event.target;
        var node = (el && el.closest) ? el.closest("div[data-role], .tab, .pc-task") : null;
        window.__pilotClicks.push({
            t: Date.now(), trusted: !!event.isTrusted,
            target: desc(el), node: desc(node),
            role: node && node.getAttribute ? node.getAttribute("data-role") : null
        });
        if (window.__pilotClicks.length > 300) { window.__pilotClicks.shift(); }
    }, true);
    return { installed: true };
})();
"""

READ_CLICKS_JS = """
return (function () {
    var list = window.__pilotClicks || [];
    window.__pilotClicks = [];
    return { clicks: list };
})();
"""


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def build_page_state_script(levels):
    payload = json.dumps(
        [{"name": lv["name"], "selector": lv["selector"], "activeClass": lv["activeClass"]} for lv in levels],
        ensure_ascii=False,
    )
    return PAGE_STATE_TMPL % payload


def fmt_dur(seconds):
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{seconds % 60:04.1f}s"


def page_key(state):
    """页面标识：(micro, activity, task) 三层 active 文本。"""
    layers = state.get("layers") or {}
    return tuple(
        (layers.get(name) or {}).get("activeText")
        for name in ("micro", "activity", "task")
    )


def page_label(state):
    layers = state.get("layers") or {}
    parts = []
    for name in ("micro", "activity", "task"):
        info = layers.get(name) or {}
        txt = info.get("activeText")
        idx = info.get("activeIndex")
        parts.append(f"{name}={txt!r}@{idx}" if txt is not None else f"{name}=None@{idx}")
    return " | ".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_COURSE_URL,
                        help="课程内容页 URL（必填：浏览器打开任一课程页后复制地址栏）")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="采样间隔（秒），需远小于切换间隔")
    parser.add_argument("--max-pages", type=int, default=64, help="最多记录多少个页面后停止")
    parser.add_argument("--max-minutes", type=float, default=180.0, help="总时长上限（分钟）")
    parser.add_argument("--login-wait", type=float, default=240.0, help="登录/人工验证等待上限（秒）")
    parser.add_argument("--page-wait", type=float, default=240.0, help="等待课程页侧栏出现的上限（秒）")
    parser.add_argument("--max-misses", type=int, default=6, help="连续多少次采样读不到控制器即停止")
    args = parser.parse_args()
    if not args.url:
        print("缺少 --url：请先用浏览器打开任一课程页，把地址栏完整 URL 传给本脚本。")
        print('示例：python scripts/brush_pilot_3min.py --url "https://ucontent.unipus.cn/...#/course-v2:..."')
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = os.path.join(BASE_DIR, "logs")
    report = {"started_at": datetime.now().isoformat(timespec="seconds"), "config": None,
              "pages": [], "summary": {}, "errors": []}
    lines = []

    def add(text):
        lines.append(text)
        log(text)

    bot = None
    try:
        add("=== 刷时长真实实测（每页 3 分钟 · 仅第一单元）===")
        add("启动 Edge（临时 profile）...")
        bot = m.UCampusBot(os.path.join(BASE_DIR, "config.json"), skip_check=True)
        driver = bot.driver

        settings = bot.config.time_brushing_settings()
        report["config"] = settings.summary()
        add(f"生效配置：{settings.summary()}")

        add("账号密码登录中（如弹出人机验证，请在弹出的浏览器中手动完成）...")
        login_ok = bot._login()
        add(f"登录返回：{login_ok}")
        if not login_ok:
            add("⚠ 登录未确认成功：若为人机验证，请在浏览器内完成；本脚本等待页面就绪期内可人工接管")
        add(f"当前 URL：{driver.current_url}")

        add("打开课程内容页...")
        driver.get(args.url)
        time.sleep(3)

        def sidebar_ready():
            try:
                return bool(driver.execute_script(
                    "return document.querySelectorAll('div[data-role=\"micro\"]').length;"))
            except Exception:
                return False

        deadline = time.time() + args.page_wait
        ready = False
        while time.time() < deadline:
            if sidebar_ready():
                ready = True
                break
            time.sleep(3)
        if not ready:
            add("✗ 页面未出现侧栏（未进入具体课程任务页），实测终止——在登录页空转只会产出误导结论")
            report["errors"].append("page-not-ready")
            return _finish(report, lines, logs_dir, stamp)

        micros = driver.execute_script(
            "return document.querySelectorAll('div[data-role=\"micro\"]').length;")
        add(f"页面就绪：侧栏 micro 节点 {micros} 个")

        # 安装点击记录器（注入控制器之前）
        tap = driver.execute_script(CLICK_TAP_JS)
        add(f"点击记录器：{tap}")

        levels = settings.as_controller_options()["levels"]
        state_js = build_page_state_script(levels)
        # 注入前的页面标识：用于判断「归位」是否已经生效（见下方的等待循环）
        pre_key = page_key(driver.execute_script(state_js) or {})

        runner = tb.TimeBrushingRunner(
            driver, settings=settings, log=lambda msg: add("  [runner] " + str(msg)),
            guard=tb.ModeGuard(), poll_interval=20.0,
        )
        started = runner.start()
        add(f"挂机启动：{started}")
        if not started:
            report["errors"].append("runner-start-failed")
            return _finish(report, lines, logs_dir, stamp)

        # 归位点击后 DOM 需要一次渲染才更新：等到页面标识真正变化再建立首条记录，
        # 否则报告第 1 页会记成范围外的旧页面（2026-11-27 实测踩到）
        align_deadline = time.time() + 8.0
        while time.time() < align_deadline:
            probe = driver.execute_script(state_js) or {}
            if page_key(probe) != pre_key:
                break
            time.sleep(0.5)

        t0 = time.time()
        prev_key = None
        prev_ts = None
        cur = None                 # 当前页面记录
        misses = 0
        stop_reason = None
        sample_count = 0
        last_tick = 0
        first_interval = None

        add("")
        add("开始逐页计时（采样 %.1fs 一次；页面切换以控制器 tick 递增为准）" % args.poll_seconds)

        # 初始页面必须单独采样建立 cur：否则「起始页」永远不会被记录，
        # 第一页的 label/进入时刻会整体偏移一个 tick（2026-09-20 实测踩到）。
        try:
            init_status = runner.session.status()
            init_state = driver.execute_script(state_js) or {}
        except Exception as exc:  # noqa: BLE001
            add(f"⚠ 初始采样失败：{type(exc).__name__}: {exc}")
            init_status, init_state = {}, {}
        prev_ts = time.time()
        last_tick = init_status.get("ticks") or 0
        cur = {
            "index": 1,
            "enter_at": datetime.now().strftime("%H:%M:%S"),
            "enter_t": round(prev_ts - t0, 1),
            "enter_abs": prev_ts,
            "label": page_label(init_state),
            "key": list(page_key(init_state)),
            "ticks": last_tick,
            "clicks": [],
            "contentMark": init_state.get("contentMark"),
            "url": init_state.get("url"),
        }
        add(f"起始页面：{cur['label']}")

        while True:
            elapsed = time.time() - t0
            if elapsed > args.max_minutes * 60:
                stop_reason = f"达到总时长上限 {args.max_minutes:g} 分钟"
                break

            try:
                status = runner.session.status()
                state = driver.execute_script(state_js) or {}
                clicks = (driver.execute_script(READ_CLICKS_JS) or {}).get("clicks", [])
            except Exception as exc:  # noqa: BLE001
                misses += 1
                add(f"⚠ 采样异常({misses}/{args.max_misses})：{type(exc).__name__}: {str(exc)[:80]}")
                if misses >= args.max_misses:
                    stop_reason = f"连续 {misses} 次采样异常"
                    break
                time.sleep(args.poll_seconds)
                continue

            sample_count += 1
            if not status.get("injected"):
                misses += 1
                if misses >= args.max_misses:
                    stop_reason = f"控制器连续 {misses} 次不在页面内"
                    break
            else:
                misses = 0

            ticks = status.get("ticks") or 0
            key = page_key(state)
            now = time.time()

            # tick 递增 = 控制器完成一次切换 → 上一页结束、新页开始
            if ticks != last_tick:
                if prev_ts is not None and first_interval is None and ticks > last_tick:
                    first_interval = now - prev_ts
                # 关闭上一页
                if cur is not None:
                    cur["leave_at"] = datetime.now().strftime("%H:%M:%S")
                    cur["leave_t"] = round(now - t0, 1)
                    cur["dwell_seconds"] = round(now - cur["enter_abs"], 1)
                    add(f"  [{len(report['pages']) + 1:>2}] 停留 {fmt_dur(cur['dwell_seconds']):>9} | "
                        f"{cur['label']}")
                    report["pages"].append(cur)
                    if len(report["pages"]) >= args.max_pages:
                        stop_reason = f"达到页面数上限 {args.max_pages}"
                        last_tick = ticks
                        cur = None          # 已归档，置空以免循环外重复追加（2026-09-20 实测踩到）
                        break
                # 开启新页
                cur = {
                    "index": len(report["pages"]) + 1,
                    "enter_at": datetime.now().strftime("%H:%M:%S"),
                    "enter_t": round(now - t0, 1),
                    "enter_abs": now,
                    "label": page_label(state),
                    "key": list(key),
                    "ticks": ticks,
                    "clicks": [],
                    "contentMark": state.get("contentMark"),
                    "url": state.get("url"),
                }
                prev_key = key
                prev_ts = now
                last_tick = ticks

            if cur is not None and clicks:
                for c in clicks:
                    cur["clicks"].append({
                        "t": round(now - t0, 1), "trusted": c.get("trusted"),
                        "role": c.get("role"), "node": (c.get("node") or {}).get("text"),
                        "nodeCls": (c.get("node") or {}).get("cls"),
                    })

            if status.get("finished"):
                stop_reason = "控制器报告 finished（第一单元刷完，未开启循环）"
                if cur is not None:
                    cur["leave_at"] = datetime.now().strftime("%H:%M:%S")
                    cur["leave_t"] = round(now - t0, 1)
                    cur["dwell_seconds"] = round(now - cur["enter_abs"], 1)
                    report["pages"].append(cur)
                    cur = None
                break

            time.sleep(args.poll_seconds)

        # 未正常收尾的当前页也记一笔（标注被中断）
        if cur is not None:
            now = time.time()
            cur["leave_at"] = datetime.now().strftime("%H:%M:%S")
            cur["leave_t"] = round(now - t0, 1)
            cur["dwell_seconds"] = round(now - cur["enter_abs"], 1)
            cur["interrupted"] = True
            report["pages"].append(cur)

        try:
            runner.stop()
        except Exception as exc:  # noqa: BLE001
            add(f"停止 runner 时异常（忽略）：{exc}")

        total = time.time() - t0
        dwells = [p["dwell_seconds"] for p in report["pages"] if p.get("dwell_seconds")]
        report["summary"] = {
            "stop_reason": stop_reason,
            "total_seconds": round(total, 1),
            "total_pages": len(report["pages"]),
            "samples": sample_count,
            "configured_interval_min": settings.switch_interval,
            "random_interval": settings.random_interval,
            "first_switch_seconds": round(first_interval, 1) if first_interval else None,
            "dwell_min": min(dwells) if dwells else None,
            "dwell_max": max(dwells) if dwells else None,
            "dwell_avg": round(sum(dwells) / len(dwells), 1) if dwells else None,
            "clicks_total": sum(len(p.get("clicks") or []) for p in report["pages"]),
        }

        add("")
        add("=== 实测结果 ===")
        add(f"结束原因：{stop_reason}")
        add(f"总耗时：{fmt_dur(total)} | 记录页面：{len(report['pages'])} 个 | 采样：{sample_count} 次")
        s = report["summary"]
        add(f"配置间隔：{settings.switch_interval:g} 分钟（随机化={'开' if settings.random_interval else '关'}）")
        if s["first_switch_seconds"]:
            add(f"首次切换耗时：{s['first_switch_seconds']}s（配置值 {settings.switch_interval * 60:.0f}s）")
        if dwells:
            add(f"每页停留：最短 {fmt_dur(s['dwell_min'])} / 最长 {fmt_dur(s['dwell_max'])} / "
                f"均值 {fmt_dur(s['dwell_avg'])}")
        add(f"累计点击：{s['clicks_total']} 次")
        add("")
        add("页面明细（序号 | 进入 | 离开 | 停留 | 页面标识 | 点击）：")
        for p in report["pages"]:
            mark = " ⚠中断" if p.get("interrupted") else ""
            add(f"  [{p['index']:>2}] {p['enter_at']} → {p['leave_at']} | "
                f"{fmt_dur(p['dwell_seconds']):>9} | {p['label']} | {len(p.get('clicks') or [])} 次{mark}")

    except Exception as exc:  # noqa: BLE001
        import traceback
        report["errors"].append(f"fatal: {type(exc).__name__}: {exc}")
        add(f"致命错误：{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        return _finish(report, lines, logs_dir, stamp, bot)


def _finish(report, lines, logs_dir, stamp, bot=None):
    """落盘 + 关浏览器。幂等：finally 与早退路径都可能调用，第二次直接返回。"""
    if report.get("_flushed"):
        return 0
    report["_flushed"] = True
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    lines.append("")
    lines.append(f"错误清单：{report['errors'] or '无'}")

    # 落盘
    try:
        os.makedirs(logs_dir, exist_ok=True)
        json_path = os.path.join(logs_dir, f"pilot_3min_{stamp}.json")
        txt_path = os.path.join(logs_dir, f"pilot_3min_{stamp}.txt")
        payload = {k: v for k, v in report.items() if not k.startswith("_")}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"结果已落盘：{json_path}")
        log(f"可读报告：{txt_path}")
    except Exception as exc:  # noqa: BLE001
        log(f"落盘失败：{exc}")

    if bot is not None and getattr(bot, "driver", None) is not None:
        try:
            bot.driver.quit()
            log("浏览器已关闭")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
