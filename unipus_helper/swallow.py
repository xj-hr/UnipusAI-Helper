# -*- coding: utf-8 -*-
"""被忽略异常的记录与「热点升级」入口（缺陷台账 D-01）。

背景：项目里大量 `except ...: pass` 会把失败吞掉，线上表现是「什么都没发生」。
`log_swallowed()` 保持原有「继续执行」语义，但至少留下痕迹，并在同一位置反复
忽略时升级为可被上层消费的告警（SwallowAlert），让失败能**传导**到界面与状态，
而不只是躺在 DEBUG 日志里。

分级：
- 默认 DEBUG：预期内的异常（stale element、重渲染）不污染常规日志；
- 同一位置累计到 `DEFAULT_ALERT_THRESHOLD`（20）次：记一条 WARNING，并推送一条
  告警到待消费队列；`log_swallowed()` 同时返回 True，供调用方当场处理；
- 上层可随时 `drain_alerts()` 取走告警、`hotspots()` 看排行，决定要不要影响任务状态。

用法：
    except Exception:
        if log_swallowed("AISolver._wait_ready:1234"):
            ...            # 可选：本次刚好跨过阈值，做额外处置
"""
from __future__ import annotations

import logging
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List

logger = logging.getLogger("UnipusAI.Swallowed")

#: 同一位置累计多少次后升级为告警
DEFAULT_ALERT_THRESHOLD = 20

#: 兼容旧调用名
WARN_EVERY = DEFAULT_ALERT_THRESHOLD

#: 各位置累计忽略次数
_COUNTS: Dict[str, int] = {}

#: 已推送过告警的位置，避免同一位置反复刷告警
_ALERTED: set = set()

#: 待消费的告警队列（上层 drain 后清空）
_ALERTS: Deque["SwallowAlert"] = deque(maxlen=200)


@dataclass(frozen=True)
class SwallowAlert:
    """一次「热点升级」记录，供界面或任务状态消费。"""

    context: str
    count: int
    exc_type: str
    message: str
    at: float

    def as_dict(self) -> dict:
        return {"context": self.context, "count": self.count, "type": self.exc_type,
                "message": self.message, "at": self.at}


def log_swallowed(context: str, warn_every: int = DEFAULT_ALERT_THRESHOLD) -> bool:
    """记录一次「异常被忽略」。必须在 except 块内调用才能拿到异常对象。

    返回 True 表示本次恰好跨过阈值并已推送告警（调用方据此决定是否影响状态）。
    """
    exc = sys.exc_info()[1]
    count = _COUNTS.get(context, 0) + 1
    _COUNTS[context] = count
    detail = f"{type(exc).__name__}: {exc}" if exc is not None else "无异常对象"
    threshold = max(1, int(warn_every))
    if count >= threshold and context not in _ALERTED:
        _ALERTED.add(context)
        _ALERTS.append(SwallowAlert(context=context, count=count,
                                    exc_type=type(exc).__name__ if exc is not None else "None",
                                    message=str(exc)[:300] if exc is not None else "",
                                    at=time.time()))
        logger.warning("[忽略×%d] %s | %s（同一位置反复忽略，建议排查）", count, context, detail)
        return True
    logger.debug("[忽略] %s | %s", context, detail)
    return False


def drain_alerts() -> List[SwallowAlert]:
    """取走并清空待消费告警。"""
    alerts = list(_ALERTS)
    _ALERTS.clear()
    return alerts


def pending_alert_count() -> int:
    return len(_ALERTS)


def hotspots(min_count: int = DEFAULT_ALERT_THRESHOLD, limit: int = 20) -> List[dict]:
    """按忽略次数排序的热点列表，用于「逐个升级」：从最高频的位置开始处理。"""
    rows = [{"context": ctx, "count": n} for ctx, n in _COUNTS.items() if n >= max(1, min_count)]
    rows.sort(key=lambda r: (-r["count"], r["context"]))
    return rows[:limit]


def swallowed_counts() -> Dict[str, int]:
    """返回各位置的忽略次数快照。"""
    return dict(_COUNTS)


def reset_counts(clear_alerts: bool = True) -> None:
    """清空计数（测试或单次诊断使用）。"""
    _COUNTS.clear()
    _ALERTED.clear()
    if clear_alerts:
        _ALERTS.clear()
