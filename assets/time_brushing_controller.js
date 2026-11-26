/**
 * TimeBrushingController —— U 校园「刷时长」调度器
 *
 * 设计目标（面向二次开发）：
 *   1. 无外部依赖，仅需 DOM + setTimeout → 可原样投放到油猴脚本，也可经 page.evaluate 投放进 Puppeteer
 *   2. 配置全部做类型归一化（字符串 "3" 与数字 3 等价），避免 webpack/babel 产物里 switch 严格比较失配
 *   3. 范围(单元)边界基于「实际 DOM 章节数」计算，不再硬编码 6 章/单元
 *   4. 每个 tick 只做一次有效切换（最内层优先），杜绝一次 tick 连点多层 + 末尾回跳第一章
 *
 * 用法（浏览器/油猴）：
 *   const c = new TimeBrushingController({ switchLevel: 3, switchInterval: 5 });
 *   c.start();
 *
 * 用法（Puppeteer，在页面上下文内跑）：
 *   await page.evaluate(controllerSource + `;window.__tb = new TimeBrushingController({...});window.__tb.start();`)
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.TimeBrushingController = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    var DEFAULT_LEVELS = [
        { name: "chapter", selector: "#sidemenu li.group", activeClass: "active" },
        { name: "section", selector: "#header .TabsBox li", activeClass: "active" },
        { name: "tab", selector: "[class*='circleTabsBox'] a", activeClass: "selected" },
    ];

    var DEFAULTS = {
        levels: DEFAULT_LEVELS,
        switchLevel: 3,
        switchInterval: 5,
        randomInterval: true,
        range: true,
        rangeStart: 1,
        rangeEnd: 8,
        chaptersPerUnit: 6,
        loop: true,
        minIntervalMs: 30000,
        maxConsecutiveErrors: 3,
        maxIdleTicks: 5,
        // 点击方式：本站在单次 el.click() 下不响应（2026-09-17 真机实测：一级 Tab 被点了 9 次、
        // active 一次都没变），需补 mouseover/mousedown/mouseup —— 与项目 PopupWatcher 同源做法。
        // 可选值："events"（默认，多重派发）、"native"（只调 el.click()，便于对照排查）
        clickMode: "events",
        // 某层连续多少次「点了但 active 没变」后禁用该层，避免长时间空转在无效层
        maxLayerMisses: 3,
        dismissDialog: { selector: "div[class*='dialog-header-pc']", delayMs: 5000 },
        onLog: null,
        onStop: null,
    };

    function num(value, fallback) {
        var n = typeof value === "number" ? value : parseFloat(String(value));
        return isFinite(n) ? n : fallback;
    }

    function bool(value, fallback) {
        if (typeof value === "boolean") return value;
        if (typeof value === "string") return value === "true" || value === "1";
        if (value === undefined || value === null) return fallback;
        return Boolean(value);
    }

    function clamp(n, min, max) {
        return Math.min(Math.max(n, min), max);
    }

    function TimeBrushingController(options) {
        var o = options || {};
        var env = o.env || (typeof window !== "undefined" ? window : globalThis);
        if (!env || !env.document) throw new Error("TimeBrushingController: 缺少 env.document");

        this.doc = env.document;
        this.setTimeout = o.setTimeout || env.setTimeout.bind(env);
        this.clearTimeout = o.clearTimeout || env.clearTimeout.bind(env);
        this.log = typeof o.onLog === "function" ? o.onLog : function () {};

        this.options = o;
        this.levels = (o.levels || DEFAULTS.levels).slice();
        this.switchLevel = clamp(Math.round(num(o.switchLevel, DEFAULTS.switchLevel)), 1, this.levels.length);
        this.switchInterval = num(o.switchInterval, DEFAULTS.switchInterval);
        if (!(this.switchInterval > 0)) this.switchInterval = DEFAULTS.switchInterval; // 防 "" / "abc" → 0ms 空转
        this.randomInterval = bool(o.randomInterval, DEFAULTS.randomInterval);
        this.range = bool(o.range, DEFAULTS.range);
        this.loop = bool(o.loop, DEFAULTS.loop);
        this.chaptersPerUnit = Math.max(1, Math.round(num(o.chaptersPerUnit, DEFAULTS.chaptersPerUnit)));
        this.minIntervalMs = Math.max(1000, num(o.minIntervalMs, DEFAULTS.minIntervalMs));
        this.maxConsecutiveErrors = num(o.maxConsecutiveErrors, DEFAULTS.maxConsecutiveErrors);
        this.maxIdleTicks = num(o.maxIdleTicks, DEFAULTS.maxIdleTicks);
        this.clickMode = o.clickMode === "native" ? "native" : DEFAULTS.clickMode;
        this.maxLayerMisses = Math.max(1, Math.round(num(o.maxLayerMisses, DEFAULTS.maxLayerMisses)));
        this.dismissDialog = o.dismissDialog === false ? null : (o.dismissDialog || DEFAULTS.dismissDialog);
        this.onStop = typeof o.onStop === "function" ? o.onStop : function () {};

        this.rangeStart = clamp(Math.round(num(o.rangeStart, DEFAULTS.rangeStart)), 1, Number.MAX_SAFE_INTEGER);
        this.rangeEnd = clamp(Math.round(num(o.rangeEnd, DEFAULTS.rangeEnd)), this.rangeStart, Number.MAX_SAFE_INTEGER);

        this.running = false;
        this.finished = false;
        this.timerId = null;
        this.tickCount = 0;
        this.errorCount = 0;
        this.idleTicks = 0;
        //: 层级空转熔断状态：misses[i] = 第 i 层连续「点了但 active 未变」的次数
        this.misses = [];
        this.disabledLevels = [];
        this._pending = null;
    }

    /* ------------------------------ 读取层 ------------------------------ */

    TimeBrushingController.prototype.queryAll = function (selector) {
        var list = this.doc.querySelectorAll(selector);
        return Array.prototype.slice.call(list);
    };

    /** 返回指定层级当前 active 元素的下标，找不到返回 -1 */
    TimeBrushingController.prototype.activeIndex = function (level) {
        var items = this.queryAll(level.selector);
        for (var i = 0; i < items.length; i++) {
            if (items[i].classList && items[i].classList.contains(level.activeClass)) return i;
        }
        return -1;
    };

    /**
     * 多重事件派发点击。
     * 背景（2026-09-17 真机实测）：一级 Tab 被程序化 el.click() 点了 9 次，active 类一次都没换，
     * 而本项目自身的 PopupWatcher 就是用 mouseover→mousedown→mouseup→click 才点得动本站点按钮。
     * click 只发一次：先派发前三者，再由 el.click() 派发真正的 click（避免重复触发）。
     */
    TimeBrushingController.prototype.dispatchClick = function (el) {
        if (!el) return false;
        var fired = false;
        if (this.clickMode === "events" && typeof el.dispatchEvent === "function") {
            var names = ["mouseover", "mousedown", "mouseup"];
            for (var i = 0; i < names.length; i++) {
                try {
                    var event;
                    if (typeof MouseEvent === "function") {
                        event = new MouseEvent(names[i], { bubbles: true, cancelable: true, view: el.ownerDocument ? el.ownerDocument.defaultView : null });
                    } else if (this.doc && typeof this.doc.createEvent === "function") {
                        event = this.doc.createEvent("MouseEvents");
                        event.initEvent(names[i], true, true);
                    }
                    if (event) { el.dispatchEvent(event); fired = true; }
                } catch (e) { /* 事件构造失败则退回 el.click() */ }
            }
        }
        if (typeof el.click === "function") {
            el.click();
            fired = true;
        } else if (typeof el.dispatchEvent === "function") {
            if (this.doc && typeof this.doc.createEvent === "function") {
                var fallback = this.doc.createEvent("MouseEvents");
                fallback.initEvent("click", true, true);
                el.dispatchEvent(fallback);
                fired = true;
            }
        }
        return fired;
    };

    /** 解析真正的点击目标：层级可配 clickTarget（如内层 .pc-tab-view-container），找不到则退回元素本身 */
    TimeBrushingController.prototype.resolveClickTarget = function (el, level) {
        var selector = level && level.clickTarget;
        if (selector && el && typeof el.querySelector === "function") {
            try {
                var inner = el.querySelector(selector);
                if (inner) return inner;
            } catch (e) { /* 选择器非法时退回元素本身 */ }
        }
        return el;
    };

    TimeBrushingController.prototype.clickItem = function (level, index) {
        var items = this.queryAll(level.selector);
        if (!items.length) return false;
        var idx = clamp(index, 0, items.length - 1);
        var el = items[idx];
        var before = this.activeIndex(level);
        var clicked = this.dispatchClick(this.resolveClickTarget(el, level));
        if (!clicked) return false;
        // 记下「点击前该层的 active 下标」，由下一次 tick 开头核验效果（跨 tick 判定，避免误判渲染延迟）
        this._pending = { levelIndex: this.levels.indexOf(level), before: before };
        return true;
    };

    /**
     * 核验上一次点击是否真的改变了该层的 active 状态；连续 maxLayerMisses 次无效则禁用该层。
     * 依据（2026-09-17 真机归因复验）：activity 层被点击 9 次、active 从未变化 → 空转。
     */
    TimeBrushingController.prototype.verifyPending = function () {
        var pending = this._pending;
        this._pending = null;
        if (!pending || pending.levelIndex < 0) return;
        var level = this.levels[pending.levelIndex];
        if (!level) return;
        var now = this.activeIndex(level);
        if (now !== pending.before) {
            this.misses[pending.levelIndex] = 0;
            return;
        }
        var misses = (this.misses[pending.levelIndex] || 0) + 1;
        this.misses[pending.levelIndex] = misses;
        this.log(level.name + " 层点击后 active 未变化（" + misses + "/" + this.maxLayerMisses + "）");
        if (misses >= this.maxLayerMisses) {
            this.disabledLevels[pending.levelIndex] = true;
            this.log(level.name + " 层连续 " + misses + " 次点击无效，已跳过该层");
        }
    };

    /* ------------------------------ 边界计算 ------------------------------ */

    /**
     * 计算章节层级的闭区间下标 [start, end]。
     * 依据：单元序号 × 每单元章节数（chaptersPerUnit），并夹紧到真实 DOM 章节数范围内。
     */
    TimeBrushingController.prototype.chapterBounds = function () {
        var total = this.queryAll(this.levels[0].selector).length;
        if (!total) return { start: 0, end: 0, total: 0 };
        if (!this.range) return { start: 0, end: total - 1, total: total };
        var start = (this.rangeStart - 1) * this.chaptersPerUnit;
        var end = this.rangeEnd * this.chaptersPerUnit - 1;
        return {
            start: clamp(start, 0, total - 1),
            end: clamp(end, 0, total - 1),
            total: total,
        };
    };

    /* ------------------------------ 进度描述 ------------------------------ */

    /** 取元素可读文本（折叠空白 + 截断），供日志里标明「正在刷什么」 */
    TimeBrushingController.prototype.itemText = function (el, max) {
        if (!el) return null;
        var text = (el.textContent || "").replace(/\s+/g, " ").trim();
        if (!text) return null;
        var limit = max || 26;
        return text.length > limit ? text.slice(0, limit) + "…" : text;
    };

    /**
     * 节次进度：最外层（受 range 约束的那层）当前是第几节 / 共几节。
     * 背景（2026-09-28）：原日志只有「归位 / 熔断 / 已完成」这类事件，
     * 看不到「正在刷哪一节、推进到哪了」，挂机过程对用户是黑盒。
     */
    TimeBrushingController.prototype.progressLabel = function () {
        var bounds = this.chapterBounds();
        if (!bounds.total) return "共 0 节";
        var total = bounds.end - bounds.start + 1;
        var idx = this.activeIndex(this.levels[0]);
        if (idx < 0) return "未定位 / 共 " + total + " 节";
        // 越界时如实说明「不在范围内」，不要 clamp 成边界值假装正常
        if (idx < bounds.start || idx > bounds.end) {
            return "范围外（第 " + (idx + 1) + " 个节点）/ 共 " + total + " 节";
        }
        return "第 " + (idx - bounds.start + 1) + "/" + total + " 节";
    };

    /** 各层「名称 [序号/总数]」串，从外到内，用于完整标识当前页面位置 */
    TimeBrushingController.prototype.describePosition = function () {
        var self = this;
        var parts = [];
        this.levels.forEach(function (level) {
            var items = self.queryAll(level.selector);
            var idx = self.activeIndex(level);
            if (idx < 0) {
                parts.push(level.name + ": 未定位(共 " + items.length + ")");
                return;
            }
            var name = self.itemText(items[idx], 26);
            parts.push((name ? '"' + name + '" ' : "") + "[" + (idx + 1) + "/" + items.length + "]");
        });
        return parts.join(" · ");
    };

    /** 一行式进度日志：节次 + 各层位置（DOM 异常时降级为提示，不打断挂机） */
    TimeBrushingController.prototype.progressLine = function () {
        try {
            return this.progressLabel() + " | " + this.describePosition();
        } catch (e) {
            return "位置读取失败：" + (e && e.message ? e.message : e);
        }
    };

    /* ------------------------------ 调度层 ------------------------------ */

    TimeBrushingController.prototype.nextInterval = function () {
        var rate = 1;
        if (this.randomInterval) rate = Math.max(0.5, Math.random());
        return Math.max(this.minIntervalMs, this.switchInterval * rate * 60 * 1000);
    };

    /**
     * 推进内层（下标 >= 1）第 i 层。
     * @returns {boolean} 是否发生了切换；false 表示该层已到末尾，需要外层接管
     */
    TimeBrushingController.prototype.advanceLevel = function (i) {
        if (this.disabledLevels[i]) return false;
        var level = this.levels[i];
        var items = this.queryAll(level.selector);
        if (items.length < 2) return false;
        var idx = this.activeIndex(level);
        if (idx < 0) return this.clickItem(level, 0);
        if (idx + 1 > items.length - 1) return false;
        return this.clickItem(level, idx + 1);
    };

    /**
     * 推进章节（最外层），受 range / loop 约束。
     * @returns {boolean} 是否发生了切换
     */
    TimeBrushingController.prototype.advanceChapter = function () {
        if (this.disabledLevels[0]) return false;
        var level = this.levels[0];
        var bounds = this.chapterBounds();
        if (!bounds.total) return false;
        var idx = this.activeIndex(level);

        // 未定位 或 位于范围之前/之后 = 「越界」，一律归位到范围起点。
        // 注意区分 idx > bounds.end（越界，归位）与 idx === bounds.end（正好好在范围内最后一章，
        // 才受 loop 约束）：原实现把两者混为一谈，导致「停在最后一单元」被误判为已刷完。
        if (idx < 0 || idx < bounds.start || idx > bounds.end) {
            return this.clickItem(level, bounds.start);
        }
        if (idx >= bounds.end) {   // 此时等价于 idx === bounds.end
            if (!this.loop) {
                this.log("已到范围末端且未开启循环，任务结束");
                this.stop(true);
                return false;
            }
            return this.clickItem(level, bounds.start);
        }
        return this.clickItem(level, idx + 1);
    };

    /** 执行一次调度：最内层优先，一层切换成功即结束本 tick */
    TimeBrushingController.prototype.tick = function () {
        this.tickCount += 1;
        this.verifyPending();  // 先核验上一次点击是否真的生效（无效则累计，达上限禁用该层）
        var acted = false;
        for (var i = this.switchLevel - 1; i >= 1; i--) {
            if (this.advanceLevel(i)) { acted = true; break; }
        }
        if (!acted) acted = this.advanceChapter();

        if (acted) {
            this.idleTicks = 0;
            // 每次成功切换都报位置：用户据此判断「正在刷第几节、刷到哪一步」
            this.log("▶ " + this.progressLine());
        } else {
            this.idleTicks += 1;
            this.log("… 本次未发生切换（" + this.idleTicks + "/" + this.maxIdleTicks + "）：" +
                     this.progressLine());
            if (this.idleTicks >= this.maxIdleTicks) {
                this.log("连续 " + this.idleTicks + " 次未发生切换，判定页面已无目标，停止");
                this.stop(true);
            }
        }
        return acted;
    };

    TimeBrushingController.prototype.schedule = function () {
        var self = this;
        var delay = this.nextInterval();
        this.timerId = this.setTimeout(function () {
            if (!self.running) return;
            try {
                self.tick();
                self.errorCount = 0;
            } catch (e) {
                self.errorCount += 1;
                self.log("tick 异常(" + self.errorCount + "/" + self.maxConsecutiveErrors + ")：" + (e && e.message ? e.message : e));
                if (self.errorCount >= self.maxConsecutiveErrors) {
                    self.log("连续异常达到上限，停止");
                    self.stop(true);
                    return;
                }
            }
            if (self.running) self.schedule();
        }, delay);
        return delay;
    };

    /**
     * 归位：把最外层（受 range 约束）导航到范围起点。
     *
     * 背景（2026-09-20 真机实测归因）：原实现假设「启动时当前页已在 range 范围内」。
     * tick 先推内层，只有内层全部到头才调 advanceChapter()；若启动时最外层 activeIndex
     * 已越过 bounds.end（例如停在最后一单元而 range=[1,1]），advanceChapter() 会因
     * loop=false 直接判定「已到范围末端」并 stop(true) → range 形同虚设，
     * 目标单元从未被访问（实测：3 页全部落在 micro@91，第一单元 0 次访问）。
     *
     * @returns {boolean} 是否发起了归位点击
     */
    TimeBrushingController.prototype.alignToRange = function () {
        var level = this.levels[0];
        if (!level) return false;
        // 归位是「尽力而为」：DOM 异常时不阻断启动，交由后续 tick 的熔断机制处理。
        // （原 start() 完全不碰 DOM，若这里放任异常冒泡会让 start() 直接失败。）
        try {
            var bounds = this.chapterBounds();
            if (!bounds.total) return false;
            var idx = this.activeIndex(level);
            if (idx >= bounds.start && idx <= bounds.end) return false; // 已在范围内
            this.log("当前位置 " + idx + " 不在范围 [" + bounds.start + ", " + bounds.end +
                     "] 内，归位到 " + bounds.start);
            return this.clickItem(level, bounds.start);
        } catch (e) {
            this.log("启动归位失败（已忽略，交由 tick 处理）：" + (e && e.message ? e.message : e));
            return false;
        }
    };

    TimeBrushingController.prototype.start = function () {
        if (this.running) return false;
        this.running = true;
        this.finished = false;
        this.idleTicks = 0;
        this.errorCount = 0;
        this.misses = [];
        this.disabledLevels = [];
        this._pending = null;
        this.alignToRange();   // 启动即归位（不再等内层推完才由 advanceChapter 发现越界）
        var delay = this.schedule();
        this.log("挂机已启动，首次切换间隔 " + Math.round(delay / 1000) + "s");
        this.log("起始位置：" + this.progressLine());
        if (this.dismissDialog) this.handleDialog();
        return true;
    };

    TimeBrushingController.prototype.stop = function (finished) {
        this.running = false;
        this.finished = Boolean(finished);
        if (this.timerId !== null) this.clearTimeout(this.timerId);
        this.timerId = null;
        this.log("挂机已停止" + (finished ? "（正常结束）" : "") +
                 "，累计切换 " + this.tickCount + " 次，最后位置：" + this.progressLine());
        this.onStop(this.finished);
    };

    /** 关闭站点的「开始学习」类弹窗 */
    TimeBrushingController.prototype.handleDialog = function () {
        var self = this;
        var cfg = this.dismissDialog;
        if (!cfg || !cfg.selector) return;
        this.setTimeout(function () {
            try {
                var header = self.doc.querySelector(cfg.selector);
                if (!header) return;
                var host = header.parentElement || header;
                var btn = host.querySelector("button");
                if (btn) btn.click();
            } catch (e) { /* 弹窗不存在属正常情况 */ }
        }, num(cfg.delayMs, DEFAULTS.dismissDialog.delayMs));
    };

    TimeBrushingController.DEFAULTS = DEFAULTS;
    return TimeBrushingController;
});
