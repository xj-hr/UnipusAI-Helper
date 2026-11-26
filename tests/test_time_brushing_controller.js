#!/usr/bin/env node
/**
 * TimeBrushingController 行为验证（假 DOM + 假定时器，无浏览器）
 *
 * 用法：node tests/test_time_brushing_controller.js
 * 退出码：0 = 全部用例通过；1 = 存在失败用例
 *
 * 来源：F:\UnipusHelper\.workbuddy\tools\proposed\test-time-controller.js
 *      （sha256 68dbb342dc51fbdcb259…，逐字节复制，仅修正 require 路径）
 */
const CTRL = require("../assets/time_brushing_controller.js");

/* ------------------------------ 假 DOM ------------------------------ */

function mkEl(tag, cls) {
    const el = {
        tagName: String(tag).toUpperCase(),
        style: {}, value: "", children: [], parentElement: null,
        classes: new Set(cls ? [cls] : []),
        appendChild(c) { this.children.push(c); c.parentElement = this; return c; },
        addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    };
    el.classList = {
        contains: (c) => el.classes.has(c),
        add: (c) => el.classes.add(c),
        remove: (c) => el.classes.delete(c),
    };
    el.querySelector = (sel) => el.children.find((c) => c.tagName === "BUTTON") || null;
    el.querySelectorAll = () => [];
    return el;
}

/**
 * 构造模拟页面：章节点击后会重置内层（section/tab）到第 0 项，模拟 SPA 路由行为
 */
function buildPage({ chapters = 12, sections = 2, tabs = 3, activeChapter = 0, activeSection = 0, activeTab = 0, withDialog = false } = {}) {
    const clicks = [];
    const groups = [];
    const secs = [];
    const tbs = [];

    for (let i = 0; i < chapters; i++) {
        const el = mkEl("li", i === activeChapter ? "active" : null);
        el.click = () => {
            clicks.push({ kind: "chapter", idx: i });
            groups.forEach((g) => g.classes.delete("active"));
            el.classes.add("active");
            // 章节切换 → 内层回到第 0 项
            secs.forEach((s, k) => (k === 0 ? s.classes.add("active") : s.classes.delete("active")));
            tbs.forEach((t, k) => (k === 0 ? t.classes.add("selected") : t.classes.delete("selected")));
        };
        groups.push(el);
    }
    for (let i = 0; i < sections; i++) {
        const el = mkEl("li", i === activeSection ? "active" : null);
        el.click = () => {
            clicks.push({ kind: "section", idx: i });
            secs.forEach((s) => s.classes.delete("active"));
            el.classes.add("active");
            // 切换版块 → 其内部练习 tab 回到第 0 项（建模假设）
            tbs.forEach((t, k) => (k === 0 ? t.classes.add("selected") : t.classes.delete("selected")));
        };
        secs.push(el);
    }
    for (let i = 0; i < tabs; i++) {
        const el = mkEl("a", i === activeTab ? "selected" : null);
        el.click = () => {
            clicks.push({ kind: "tab", idx: i });
            tbs.forEach((t) => t.classes.delete("selected"));
            el.classes.add("selected");
        };
        tbs.push(el);
    }

    const dialogBtn = mkEl("button");
    dialogBtn.click = () => clicks.push({ kind: "dialog-btn", idx: 0 });
    const dialogHeader = mkEl("div");
    dialogHeader.parentElement = mkEl("div");
    dialogHeader.parentElement.appendChild(dialogBtn);

    const doc = {
        createElement: (t) => mkEl(t),
        querySelector(sel) {
            if (withDialog && String(sel).includes("dialog-header-pc")) return dialogHeader;
            return null;
        },
        querySelectorAll(sel) {
            const s = String(sel);
            // 注意匹配顺序：tab 的选择器同时包含 "TabsBox" 字样，必须先判 circleTabsBox
            if (s.includes("circleTabsBox")) return tbs;
            if (s.includes("TabsBox")) return secs;
            if (s.includes("sidemenu li.group")) return groups;
            return [];
        },
    };
    const state = () => ({
        chapter: groups.findIndex((g) => g.classes.has("active")),
        section: secs.findIndex((s) => s.classes.has("active")),
        tab: tbs.findIndex((t) => t.classes.has("selected")),
    });
    return { doc, clicks, groups, secs, tabEls: tbs, tabs, state };
}

/** 假定时器：只记录不真实调度，由 driver 手动触发 */
function fakeTimers() {
    const queue = [];
    return {
        queue,
        setTimeout: (fn, delay) => { queue.push({ fn, delay }); return queue.length; },
        clearTimeout: (id) => { if (queue[id - 1]) queue[id - 1].dead = true; },
        runNext(minDelayMs = 60000) {
            const idx = queue.findIndex((t) => !t.dead && t.delay >= minDelayMs);
            if (idx < 0) return null;
            const t = queue.splice(idx, 1)[0];
            t.fn();
            return t.delay;
        },
        runDelay(delay) {
            const idx = queue.findIndex((t) => !t.dead && t.delay === delay);
            if (idx < 0) return null;
            const t = queue.splice(idx, 1)[0];
            t.fn();
            return t.delay;
        },
    };
}

/* ------------------------------ 用例框架 ------------------------------ */

let pass = 0;
let fail = 0;
const failures = [];
function check(name, actual, expected) {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a === e) { pass++; console.log(`  ok   ${name}  ${a}`); }
    else { fail++; failures.push(name); console.log(`  FAIL ${name}\n       实际 ${a}\n       期望 ${e}`); }
}
function section(title) { console.log(`\n[${title}]`); }

/* ------------------------------ T1 层级推进顺序 ------------------------------ */
section("T1 switchLevel=3：最内层优先推进，章节仅在内外层耗尽后 +1");
{
    const page = buildPage({ chapters: 12, sections: 2, tabs: 3 });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, switchInterval: 5, randomInterval: false, range: false, loop: true, switchLevel: 3, dismissDialog: false });
    ctrl.start();
    const seq = [];
    const perTick = [];
    for (let i = 0; i < 8; i++) {
        const before = page.clicks.length;
        timers.runNext();
        perTick.push(page.clicks.length - before);
        seq.push(page.state());
    }
    check("每 tick 状态序列", seq, [
        { chapter: 0, section: 0, tab: 1 },
        { chapter: 0, section: 0, tab: 2 },
        { chapter: 0, section: 1, tab: 0 },
        { chapter: 0, section: 1, tab: 1 },
        { chapter: 0, section: 1, tab: 2 },
        { chapter: 1, section: 0, tab: 0 },
        { chapter: 1, section: 0, tab: 1 },
        { chapter: 1, section: 0, tab: 2 },
    ]);
    check("每 tick 恰好 1 次点击", perTick, [1, 1, 1, 1, 1, 1, 1, 1]);
    check("定时器间隔为 5 分钟", ctrl.nextInterval(), 300000);
}

/* ------------------------------ T2 范围 + 循环回绕 ------------------------------ */
section("T2 range=[3,4]（36 章 = 6 章/单元 → 下标 12..23），起点 22，开启循环");
{
    const page = buildPage({ chapters: 36, sections: 1, tabs: 1, activeChapter: 22 });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, switchLevel: 1, range: true, rangeStart: 3, rangeEnd: 4, chaptersPerUnit: 6, loop: true, dismissDialog: false });
    ctrl.start();
    const s1 = (timers.runNext(), page.state().chapter);
    const s2 = (timers.runNext(), page.state().chapter);
    const s3 = (timers.runNext(), page.state().chapter);
    check("22 → 23（范围内推进）", s1, 23);
    check("23 → 12（到末端回绕到 startUnit）", s2, 12);
    check("12 → 13", s3, 13);
    check("章节点击轨迹", page.clicks.filter((c) => c.kind === "chapter").map((c) => c.idx), [23, 12, 13]);
}

section("T3 同上但 loop=false：末端主动停止，不再产生点击");
{
    const page = buildPage({ chapters: 36, sections: 1, tabs: 1, activeChapter: 23 });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, switchLevel: 1, range: true, rangeStart: 3, rangeEnd: 4, loop: false, dismissDialog: false });
    let stopped = null;
    ctrl.onStop = (fin) => (stopped = fin);
    ctrl.start();
    timers.runNext();
    check("已停止", ctrl.running, false);
    check("结束标记 finished=true", stopped, true);
    check("停止后无点击", page.clicks.length, 0);
    check("停止后不再排定时器", timers.runNext(), null);
}

/* ------------------------------ T4 配置归一化 ------------------------------ */
section("T4 配置归一化：字符串数字与数字等价；非法间隔不会退化成 0ms 空转");
{
    const page = buildPage({ chapters: 12, sections: 1, tabs: 1, activeChapter: 5 });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, switchLevel: "1", switchInterval: "5", range: false, dismissDialog: false });
    ctrl.start();
    timers.runNext();
    check("switchLevel=\"1\" 仍只切章节（chapter 5→6）", page.state().chapter, 6);
    check("switchInterval=\"5\" → 300000ms", ctrl.nextInterval(), 300000);

    // 范围超出真实 DOM 时夹紧到最后一章，不越界、不抛异常
    const page3 = buildPage({ chapters: 12, sections: 1, tabs: 1, activeChapter: 5 });
    const t3 = fakeTimers();
    const c3 = new CTRL({ env: { document: page3.doc }, setTimeout: t3.setTimeout, clearTimeout: t3.clearTimeout, randomInterval: false, switchLevel: 1, range: "true", rangeStart: "3", rangeEnd: "4", dismissDialog: false });
    c3.start();
    t3.runNext();
    check("rangeStart=3 超出 12 章 DOM → 夹紧到 11", page3.state().chapter, 11);

    const page2 = buildPage({ chapters: 12 });
    const t2 = fakeTimers();
    const c2 = new CTRL({ env: { document: page2.doc }, setTimeout: t2.setTimeout, clearTimeout: t2.clearTimeout, randomInterval: false, switchInterval: "", switchLevel: "", dismissDialog: false });
    c2.start();
    const d = t2.queue[0].delay;
    check("空字符串间隔被回退为默认 5 分钟（不退化为 0）", d, 300000);
    check("空字符串 switchLevel 回退为 3", c2.switchLevel, 3);
}

/* ------------------------------ T5 幂等 / 空页面 ------------------------------ */
section("T5 空页面与重复 start");
{
    const page = buildPage({ chapters: 0, sections: 0, tabs: 0 });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, switchLevel: 3, maxIdleTicks: 3, dismissDialog: false });
    ctrl.start();
    check("重复 start 返回 false", ctrl.start(), false);
    for (let i = 0; i < 3; i++) timers.runNext();
    check("连续空转后自动停止", ctrl.running, false);
    check("无点击", page.clicks.length, 0);
}

/* ------------------------------ T6 弹窗关闭 ------------------------------ */
section("T6 定时关闭「开始学习」弹窗");
{
    const page = buildPage({ chapters: 12, withDialog: true });
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, dismissDialog: { selector: "div[class*='dialog-header-pc']", delayMs: 5000 } });
    ctrl.start();
    check("已排入 5000ms 关闭定时器", timers.queue.some((t) => t.delay === 5000), true);
    timers.runDelay(5000);
    check("弹窗按钮被点击", page.clicks.some((c) => c.kind === "dialog-btn"), true);
}

/* ------------------------------ T7 异常熔断 ------------------------------ */
section("T7 tick 抛异常连续 3 次后自动熔断");
{
    const page = buildPage({ chapters: 12 });
    page.doc.querySelectorAll = () => { throw new Error("boom"); };
    const timers = fakeTimers();
    const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, maxConsecutiveErrors: 3, dismissDialog: false });
    ctrl.start();
    for (let i = 0; i < 3; i++) timers.runNext();
    check("熔断后停止", ctrl.running, false);
}

/* ------------------------------ T8 多重事件派发 ------------------------------ */
section("T8 点击改多重事件派发（真机：单次 click 点不动一级 Tab）");
{
    const page = buildPage({ chapters: 12, sections: 2, tabs: 3 });
    page.tabEls.forEach((t) => {
        t.events = [];
        t.dispatchEvent = (e) => { t.events.push(e.type); return true; };
    });
    const hadMouseEvent = typeof globalThis.MouseEvent === "function";
    if (!hadMouseEvent) {
        globalThis.MouseEvent = function (type) { this.type = type; };
    }
    try {
        const timers = fakeTimers();
        const ctrl = new CTRL({ env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout, randomInterval: false, switchLevel: 3, dismissDialog: false });
        ctrl.start();
        timers.runNext();
        const fired = page.tabEls.flatMap((t) => t.events);
        check("派发了 mouseover", fired.includes("mouseover"), true);
        check("派发了 mousedown", fired.includes("mousedown"), true);
        check("派发了 mouseup", fired.includes("mouseup"), true);
        check("仍触达真实 click 语义", page.clicks.some((c) => c.kind === "tab"), true);

        const page2 = buildPage({ chapters: 12, sections: 2, tabs: 3 });
        page2.tabEls.forEach((t) => { t.events = []; t.dispatchEvent = (e) => { t.events.push(e.type); return true; }; });
        const t2 = fakeTimers();
        const c2 = new CTRL({ env: { document: page2.doc }, setTimeout: t2.setTimeout, clearTimeout: t2.clearTimeout, randomInterval: false, switchLevel: 3, clickMode: "native", dismissDialog: false });
        c2.start();
        t2.runNext();
        check("native 模式不派发鼠标事件", page2.tabEls.flatMap((t) => t.events).length, 0);
        check("native 模式仍会点击", page2.clicks.some((c) => c.kind === "tab"), true);
    } finally {
        if (!hadMouseEvent) { delete globalThis.MouseEvent; }
    }
}

/* ------------------------------ T9 clickTarget ------------------------------ */
section("T9 层级可配 clickTarget（点内层元素）");
{
    const page = buildPage({ chapters: 12, sections: 2, tabs: 3 });
    const clicks = [];
    page.tabEls.forEach((t, i) => {
        const inner = mkEl("div");
        inner.click = () => clicks.push({ kind: "tab-inner", idx: i });
        t.querySelector = (sel) => (sel === ".pc-tab-view-container" ? inner : null);
    });
    const timers = fakeTimers();
    const ctrl = new CTRL({
        env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
        randomInterval: false, switchLevel: 3, dismissDialog: false,
        levels: [
            { name: "chapter", selector: "#sidemenu li.group", activeClass: "active" },
            { name: "section", selector: "#header .TabsBox li", activeClass: "active" },
            { name: "tab", selector: "[class*='circleTabsBox'] a", activeClass: "selected", clickTarget: ".pc-tab-view-container" },
        ],
    });
    ctrl.start();
    timers.runNext();
    check("点击落在内层 clickTarget 上", clicks.length, 1);
    check("外层 .tab 未被直接点击", page.clicks.some((c) => c.kind === "tab"), false);
}

/* ------------------------------ T10 层级空转熔断 ------------------------------ */
section("T10 层级空转熔断（本站在一级 Tab 上点击无效）");
{
    const mk = (cls) => {
        const el = {
            tagName: "DIV", classes: new Set(cls ? [cls] : []), clicked: 0,
            click() { el.clicked += 1; },
        };
        el.classList = {
            contains: (c) => el.classes.has(c),
            add: (c) => el.classes.add(c),
            remove: (c) => el.classes.delete(c),
        };
        return el;
    };
    // 最外层 micro（9 项）、中间 activity（2 项，点击无效）、最内层 task（仅 1 项）
    const micro = Array.from({ length: 9 }, (_, i) => mk(i === 0 ? "pc-menu-activity" : null));
    const broken = [mk("pc-header-tab-activity"), mk(null)];
    const task = [mk("pc-header-task-activity")];
    // 只有 activity 层点击不改变 active（复现真机：点了 Understanding，Reading 仍是 active）
    broken.forEach((el, i) => {
        el.click = () => {
            el.clicked += 1;
            broken.forEach((b, k) => (k === i ? b.classes.add("noop") : b.classes.delete("noop")));
        };
    });
    micro.forEach((el, i) => {
        el.click = () => { el.clicked += 1; micro.forEach((m, k) => (k === i ? m.classes.add("pc-menu-activity") : m.classes.delete("pc-menu-activity"))); };
    });
    const doc = {
        querySelectorAll: (sel) => {
            const s = String(sel);
            if (s.includes("micro")) return micro;
            if (s.includes("tab-row") || s.includes("pc-header-tab")) return broken;
            if (s.includes("pc-task")) return task;
            return [];
        },
        querySelector: () => null,
        createElement: (t) => mk(null),
    };
    const timers = fakeTimers();
    const ctrl = new CTRL({
        env: { document: doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
        randomInterval: false, switchLevel: 3, range: false, maxLayerMisses: 2, dismissDialog: false,
        levels: [
            { name: "micro", selector: "div[data-role='micro']", activeClass: "pc-menu-activity" },
            { name: "activity", selector: ".pc-header-tab-row > .tab", activeClass: "pc-header-tab-activity" },
            { name: "task", selector: ".pc-header-tasks-row > .pc-task", activeClass: "pc-header-task-activity" },
        ],
    });
    ctrl.start();
    timers.runNext();  // tick1：activity 被点击（无数）
    timers.runNext();  // tick2：核验 misses=1，再点 activity
    check("前两次 tick 都在点无效的 activity 层", broken.reduce((n, b) => n + b.clicked, 0), 2);
    timers.runNext();  // tick3：核验 misses=2 → 禁用 activity，改推最外层 micro
    check("达到上限后 activity 层被禁用", ctrl.disabledLevels[1], true);
    check("随后改推最外层 micro", micro.reduce((n, m) => n + m.clicked, 0), 1);
    check("micro 的 active 已推进到第 2 项", micro.findIndex((m) => m.classes.has("pc-menu-activity")), 1);
}

/* ------------------------------ T11：启动归位 ------------------------------ */

/**
 * 构造「只有最外层（micro）」的假页面，用于隔离 range / loop 行为。
 * 依据：2026-09-20 真机实测——range=[1,1] 但启动时停在 micro@91（最后一单元），
 * 原实现会因 loop=false 直接 stop(true)，第一单元 0 次访问。
 */
function mkMicroPage({ chapters = 96, activeChapter = 0 } = {}) {
    const micro = [];
    for (let i = 0; i < chapters; i++) {
        const el = mkEl("div", i === activeChapter ? "pc-menu-activity" : null);
        el.textContent = "节" + (i + 1);          // 供 itemText / describePosition 使用
        el.clicked = 0;
        el.click = () => {
            el.clicked += 1;
            micro.forEach((m, k) => (k === i ? m.classes.add("pc-menu-activity") : m.classes.delete("pc-menu-activity")));
        };
        micro.push(el);
    }
    const doc = {
        querySelectorAll: (sel) => (String(sel).includes("micro") ? micro : []),
        querySelector: () => null,
        createElement: (t) => mkEl(t),
    };
    return {
        doc, micro,
        clicked: () => micro.reduce((n, m) => n + m.clicked, 0),
        activeIndex: () => micro.findIndex((m) => m.classes.has("pc-menu-activity")),
    };
}

function mkMicroCtrl(page, overrides = {}) {
    const timers = fakeTimers();
    const ctrl = new CTRL(Object.assign({
        env: { document: page.doc }, setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
        randomInterval: false, switchLevel: 1, dismissDialog: false,
        range: true, rangeStart: 1, rangeEnd: 1, chaptersPerUnit: 16, loop: false,
        levels: [{ name: "micro", selector: "div[data-role='micro']", activeClass: "pc-menu-activity" }],
    }, overrides));
    return { ctrl, timers };
}

section("T11 启动归位（越出 range 时先归位，而非误判为已刷完）");
{
    // 范围 [1,1] → bounds [0,15]；启动时停在索引 91（范围之外）
    const page = mkMicroPage({ chapters: 96, activeChapter: 91 });
    const { ctrl } = mkMicroCtrl(page);
    ctrl.start();
    check("启动即归位到范围起点", page.activeIndex(), 0);
    check("归位仅点击 1 次", page.clicked(), 1);
    check("未误判为已结束", ctrl.finished, false);
    check("仍处于运行态", ctrl.running, true);
}

section("T11b 已在范围内则不归位");
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 5 });
    const { ctrl } = mkMicroCtrl(page);
    ctrl.start();
    check("范围内无归位点击", page.clicked(), 0);
    check("active 保持不动", page.activeIndex(), 5);
}

section("T11c 范围内最后一章 + 未开循环 → 结束（保持原行为）");
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 15 }); // 15 === bounds.end
    const { ctrl, timers } = mkMicroCtrl(page);
    ctrl.start();
    check("末端在范围内，不做归位", page.clicked(), 0);
    timers.runNext();  // tick1 → advanceChapter：idx === bounds.end 且 loop=false
    check("范围末端且未开循环 → 结束", ctrl.finished, true);
}

section("T11d 范围内最后一章 + 开循环 → 回到起点");
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 15 });
    const { ctrl, timers } = mkMicroCtrl(page, { loop: true });
    ctrl.start();
    timers.runNext();  // tick1 → 回起点
    check("循环开启时回到范围起点", page.activeIndex(), 0);
    check("未结束", ctrl.finished, false);
}

section("T11e 范围之前（idx < bounds.start）也归位");
{
    // range=[3,3] → bounds [32,47]；启动时停在索引 2（范围之前）
    const page = mkMicroPage({ chapters: 96, activeChapter: 2 });
    const { ctrl } = mkMicroCtrl(page, { rangeStart: 3, rangeEnd: 3 });
    ctrl.start();
    check("范围之前归位到 bounds.start", page.activeIndex(), 32);
}

section("T12 进度日志（节次标识）");
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 5 });
    // range=[1,2] × chaptersPerUnit=8 → bounds [0, 15]，共 16 节；当前 idx=5 → 第 6 节
    const { ctrl } = mkMicroCtrl(page, { rangeStart: 1, rangeEnd: 2, chaptersPerUnit: 8 });
    ctrl.start();
    check("progressLabel 给出节次", ctrl.progressLabel(), "第 6/16 节");
    check("describePosition 含序号", /\[6\/96\]/.test(ctrl.describePosition()), true);
    check("describePosition 含节点名", /节6/.test(ctrl.describePosition()), true);
    check("progressLine 组合节次与位置", /^第 6\/16 节 \| /.test(ctrl.progressLine()), true);
}
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 0 });
    const logs = [];
    const { ctrl, timers } = mkMicroCtrl(page, { onLog: (m) => logs.push(m) });
    ctrl.start();
    check("start 输出起始位置", logs.some((m) => m.indexOf("起始位置：第 1/16 节") === 0), true);
    logs.length = 0;                       // 清掉启动日志，只看切换
    timers.runNext();                      // tick1 → 推进到第 2 节
    const progress = logs.filter((m) => m.indexOf("▶ ") === 0);
    check("tick 后输出一行进度", progress.length, 1);
    check("进度里标明节次", /第 2\/16 节/.test(progress[0] || ""), true);
    ctrl.stop(false);
    check("stop 输出最后位置与累计次数",
        logs.some((m) => m.indexOf("挂机已停止") === 0 && m.indexOf("最后位置") > 0 && m.indexOf("累计切换") > 0),
        true);
}
{
    const page = mkMicroPage({ chapters: 96, activeChapter: 91 });
    const logs = [];
    const { ctrl } = mkMicroCtrl(page, { onLog: (m) => logs.push(m) });   // range [1,1] → bounds [0,15]
    check("越界时如实标为范围外",
        /^范围外（第 92 个节点）\/ 共 16 节$/.test(ctrl.progressLabel()), true);
    ctrl.start();                                                          // 启动归位 → 回到 idx 0
    check("启动归位日志仍在", logs.some((m) => m.indexOf("归位到 0") > 0), true);
    check("归位后节次为第 1 节", ctrl.progressLabel(), "第 1/16 节");
}

console.log(`\n通过 ${pass}，失败 ${fail}${fail ? "：" + failures.join("; ") : ""}`);
process.exit(fail ? 1 : 0);
