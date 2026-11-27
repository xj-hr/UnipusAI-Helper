# -*- coding: utf-8 -*-
"""提交按钮相关的一次性工具：网络钩子注入、提交状态读取、浮层关闭、错误摘要。

从 `UnipusAI_Helper.py` 外迁（缺陷台账 D-11 第一步）：不依赖任何类或模块全局。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .course_catalog import describe_directory_page_state
from .swallow import log_swallowed


def _format_webdriver_error(exc: Exception, driver=None) -> str:
    raw = str(exc or '').split('Stacktrace:')[0].strip()
    lines = []
    for line in raw.splitlines():
        cleaned = re.sub(r'^(?:Message:\s*)+', '', line.strip()).strip()
        if cleaned:
            lines.append(cleaned)
    detail = ' '.join(lines)
    base = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    if driver is None:
        return base
    state = describe_directory_page_state(driver)
    parts = [base]
    body_head = state.get('body_head') if isinstance(state, dict) else ''
    url = state.get('url') if isinstance(state, dict) else ''
    if isinstance(body_head, str) and body_head.strip():
        parts.append(f"页面={body_head.strip()[:50]}")
    if isinstance(url, str) and url.strip():
        parts.append(f"url={url.strip()[:100]}")
    return ' | '.join(parts)

def _dismiss_known_info_overlays(driver) -> bool:
    if driver is None:
        return False
    try:
        clicked = driver.execute_script("""
            const vis = el => !!el && !!el.getClientRects().length;
            let hit = false;
            for (const sel of ['.system-info-cloud-ok-button', '.know-box .iKnow']) {
                for (const btn of document.querySelectorAll(sel)) {
                    if (vis(btn)) {
                        btn.click();
                        hit = true;
                    }
                }
            }
            return hit;
        """)
        return clicked is True
    except Exception:
        return False

def _install_submit_network_hook(driver) -> None:
    if driver is None:
        return
    try:
        driver.execute_script("""
            const isTarget = url => /\\/(?:submit|grade\\/content)(?:[/?#]|$)/i.test(String(url || ''));
            if (!window.__unipusSubmitMonitor) {
                const state = {
                    reqCount: 0,
                    inFlight: 0,
                    gradingPending: false,
                    submitSucceeded: false,
                    lastError: '',
                    reset() {
                        this.reqCount = 0;
                        this.inFlight = 0;
                        this.gradingPending = false;
                        this.submitSucceeded = false;
                        this.lastError = '';
                    }
                };
                const inspectResponse = (url, status, bodyText) => {
                    const u = String(url || '');
                    const txt = String(bodyText || '');
                    if (status >= 400) {
                        state.lastError = 'HTTP ' + status + ' ' + u.slice(-60);
                        state.gradingPending = false;
                        return;
                    }
                    if (/icorrectId/i.test(txt) || /\\\\?"GradeStatus\\\\?":\\s*0/.test(txt)) {
                        state.gradingPending = true;
                        return;
                    }
                    if (/\\\\?"GradeStatus\\\\?":\\s*1/.test(txt)) {
                        state.gradingPending = false;
                        return;
                    }
                    if (/\\/submit(?:[/?#]|$)/i.test(u) && /"code"\\s*:\\s*0/.test(txt)) {
                        state.gradingPending = false;
                        state.submitSucceeded = true;
                        return;
                    }
                    if (/\\/grade\\/content/i.test(u) && /"code"\\s*:\\s*10/.test(txt)) {
                        state.gradingPending = true;
                    }
                };
                if (typeof window.fetch === 'function') {
                    const origFetch = window.fetch;
                    window.fetch = function(...args) {
                        const raw = args[0];
                        const url = String((raw && raw.url) || raw || '');
                        if (!isTarget(url)) return origFetch.apply(this, args);
                        state.reqCount += 1;
                        state.inFlight += 1;
                        return origFetch.apply(this, args).then(res => {
                            try {
                                res.clone().text().then(txt => {
                                    inspectResponse(url, res.status, txt);
                                }).catch(() => {});
                            } catch (_) {}
                            state.inFlight = Math.max(0, state.inFlight - 1);
                            return res;
                        }, err => {
                            state.inFlight = Math.max(0, state.inFlight - 1);
                            state.lastError = String((err && err.message) || err || 'fetch error').slice(0, 80);
                            throw err;
                        });
                    };
                }
                const origOpen = XMLHttpRequest.prototype.open;
                const origSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this.__unipusHookUrl = String(url || '');
                    return origOpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    const url = this.__unipusHookUrl || '';
                    if (isTarget(url)) {
                        state.reqCount += 1;
                        state.inFlight += 1;
                        this.addEventListener('loadend', () => {
                            state.inFlight = Math.max(0, state.inFlight - 1);
                            inspectResponse(url, this.status, this.responseText);
                        });
                    }
                    return origSend.apply(this, arguments);
                };
                window.__unipusSubmitMonitor = state;
            }
            window.__unipusSubmitMonitor.reset();
        """)
    except Exception:
        log_swallowed("_install_submit_network_hook:9808")

def _read_submit_network_state(driver) -> Optional[Dict[str, Any]]:
    if driver is None:
        return None
    try:
        res = driver.execute_script("""
            const m = window.__unipusSubmitMonitor;
            if (!m) return null;
            return {
                reqCount: Number(m.reqCount || 0),
                inFlight: Number(m.inFlight || 0),
                gradingPending: !!m.gradingPending,
                submitSucceeded: !!m.submitSucceeded,
                lastError: String(m.lastError || '')
            };
        """)
        return res if isinstance(res, dict) else None
    except Exception:
        return None

def _read_submit_progress_toast(driver) -> str:
    if driver is None:
        return ''
    try:
        res = driver.execute_script("""
            const clean = t => (t || '').replace(/\\s+/g, ' ').trim();
            const vis = el => !!el && !!el.getClientRects().length;
            return [...document.querySelectorAll('.ant-message-notice, .ant-spin-text')]
                .filter(vis)
                .map(el => clean(el.innerText))
                .filter(Boolean)
                .join(' | ');
        """)
        return res if isinstance(res, str) else ''
    except Exception:
        return ''

def _describe_submit_timeout_state(driver, net_state: Optional[Dict[str, Any]] = None) -> str:
    parts = []
    if isinstance(net_state, dict):
        parts.append(
            f"xhr(req={net_state.get('reqCount', 0)}, inFlight={net_state.get('inFlight', 0)}, "
            f"grading={net_state.get('gradingPending', False)})"
        )
        if net_state.get('lastError'):
            parts.append(f"err={net_state['lastError']}")
    if driver is None:
        return ' | '.join(parts)
    try:
        dom = driver.execute_script("""
            const clean = t => (t || '').replace(/\\s+/g, ' ').trim();
            const vis = el => !!el && !!el.getClientRects().length;
            const btns = [...document.querySelectorAll('button, a.btn, .btn')].filter(vis).slice(0, 6).map(b =>
                clean(b.innerText).slice(0, 20) + '[' + String(b.className || '').slice(0, 30) + ']'
            );
            const modals = [...document.querySelectorAll('[role="dialog"], .ant-modal, .ant-message-notice')]
                .filter(vis).slice(0, 2).map(m => clean(m.innerText).slice(0, 60));
            return {btns, modals};
        """)
        if isinstance(dom, dict):
            btns = dom.get('btns') or []
            modals = dom.get('modals') or []
            if btns:
                parts.append(f"可见按钮={btns}")
            if modals:
                parts.append(f"可见弹窗={modals}")
    except Exception:
        log_swallowed("_describe_submit_timeout_state:9879")
    return ' | '.join(parts)
