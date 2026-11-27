# -*- coding: utf-8 -*-
"""被忽略异常的记录入口（缺陷台账 D-01）。

背景：项目里大量 `except ...: pass` 把失败完全吞掉，线上表现是「什么都没发生」，
排查时只能靠猜。本模块提供 `log_swallowed()`：保持原有「继续执行」的语义，
但至少留下一条可检索的痕迹。

分级策略（与 AGENTS.md §3.3 一致）：
- 默认 DEBUG：预期内的异常（stale element、重渲染）不应污染常规日志；
- 同一位置第 `warn_every` 次（默认 20）升级为 WARNING：反复忽略说明这里有真问题。

用法（通常由批量改造生成，不需要手写）：
    except Exception:
        log_swallowed("AISolver._wait_ready:1234")
"""
from __future__ import annotations

import logging
import sys
from typing import Dict

logger = logging.getLogger("UnipusAI.Swallowed")

#: 每个位置的忽略次数；用于识别「反复被吞」的热点
_COUNTS: Dict[str, int] = {}

#: 同一位置累计这么多次后升级为 WARNING（只报一次，避免刷屏）
WARN_EVERY = 20


def log_swallowed(context: str, warn_every: int = WARN_EVERY) -> None:
    """记录一次「异常被忽略」。必须在 except 块内调用才能拿到异常对象。"""
    exc = sys.exc_info()[1]
    count = _COUNTS.get(context, 0) + 1
    _COUNTS[context] = count
    detail = f"{type(exc).__name__}: {exc}" if exc is not None else "无异常对象"
    if count == max(1, warn_every):
        logger.warning("[忽略×%d] %s | %s（同一位置反复忽略，建议排查）", count, context, detail)
    else:
        logger.debug("[忽略] %s | %s", context, detail)


def swallowed_counts() -> Dict[str, int]:
    """返回各位置的忽略次数快照，便于调试面板或探针脚本汇总。"""
    return dict(_COUNTS)


def reset_counts() -> None:
    """清空计数（仅测试或单次诊断使用）。"""
    _COUNTS.clear()
