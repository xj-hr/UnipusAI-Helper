# -*- coding: utf-8 -*-
"""纯文本工具：中文提示抽取、相似度、布尔解析、JWT 载荷解析（D-11 外迁）。

只依赖标准库，无类与全局状态。
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple


def _as_bool(value: Any, default: bool = False) -> bool:
    """兼容 JSON 布尔与字符串布尔的开关解析。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("", "none", "null"):
        return default
    return text not in ("0", "false", "no", "off", "disabled", "disable")

def _parse_auth_token(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    parsed = raw if isinstance(raw, dict) else None
    token = "" if parsed is not None else str(raw or "").strip()

    for _ in range(2):
        if parsed is not None or not token:
            break
        try:
            decoded = json.loads(token)
        except (TypeError, ValueError):
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
                token = token[1:-1].strip()
                continue
            break
        if isinstance(decoded, str):
            token = decoded.strip()
        else:
            parsed = decoded

    if isinstance(parsed, dict):
        token_info = parsed.get("tokenInfo")
        jwt = parsed.get("jwt") or parsed.get("Authorization")
        if not jwt and isinstance(token_info, dict):
            jwt = token_info.get("jwt")
        if isinstance(jwt, str) and jwt.lower().startswith("bearer "):
            jwt = jwt[7:].strip()
        if not isinstance(jwt, str) or jwt.count(".") != 2:
            return None, None

        legacy_keys = {"rt", "jwt", "rtExpire", "jwtExpire"}
        legacy = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")) \
            if legacy_keys.issubset(parsed) else None
        return legacy, jwt

    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token.count(".") == 2 and all(token.split(".")):
        return None, token
    return None, None

CJK_HINT_PATTERN = re.compile(r'[（(]\s*([\u4e00-\u9fa5][^（）()]{0,40}?)\s*[）)]')

def extract_cjk_hints(text: str) -> List[str]:
    return [hint.strip() for hint in CJK_HINT_PATTERN.findall(text or '') if hint.strip()]

def blank_cjk_hints(q: "Question") -> List[str]:
    inputs = getattr(q, 'inputs', None) or []
    count = len(inputs)
    if count <= 0:
        return []

    aligned = []
    for blank in (getattr(q, 'banked_blanks', None) or [])[:count]:
        around = f"{blank.get('right_context') or ''} {blank.get('context') or ''}"
        found = extract_cjk_hints(around)
        aligned.append(found[0] if found else '')
    if len(aligned) == count and all(aligned):
        return aligned

    hints = extract_cjk_hints(getattr(q, 'text', '') or '')
    return hints if len(hints) == count else []

def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    common = len(set(left) & set(right))
    base = max(len(set(left)), len(set(right))) or 1
    return common / base * 0.9
