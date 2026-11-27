# -*- coding: utf-8 -*-
"""录音按钮选择器与查找工具（D-11 外迁）。

站点类名是 webpack 哈希，因此这里维护多候选选择器；不依赖任何类。
"""
from __future__ import annotations

from typing import Any, List, Tuple

from selenium.webdriver.common.by import By

from .swallow import log_swallowed


RECORD_BUTTON_SELECTOR = '.record-icon.button-record'

RECORD_BUTTON_FALLBACKS = (
    '.button-record',
    '.oral-record-btn',
    '.record-btn',
    '.record-button',
    '[class*="record"][class*="btn"]',
)

def record_button_selectors() -> Tuple[str, ...]:
    return (RECORD_BUTTON_SELECTOR,) + RECORD_BUTTON_FALLBACKS

def find_record_buttons(driver, scope=None) -> List[Any]:
    root = driver if scope is None else scope
    for selector in record_button_selectors():
        try:
            buttons = root.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            log_swallowed("find_record_buttons:2153"); continue
        if not isinstance(buttons, (list, tuple)):
            continue
        usable = []
        for button in buttons:
            try:
                if not button.is_displayed():
                    continue
                size = button.size or {}
                if (size.get('width') or 0) > 180 or (size.get('height') or 0) > 180:
                    continue
            except Exception:
                log_swallowed("find_record_buttons:2165"); continue
            usable.append(button)
        if usable:
            return usable
    return []
