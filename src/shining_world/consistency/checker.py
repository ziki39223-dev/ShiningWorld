"""规则型一致性校验。

设计取舍：不额外消耗模型调用（免费 API 池额度宝贵），先用确定性规则拦截
最危险的几类问题——禁用词、硬性规则冲突、时序倒挂。模型级语义校验留给
可选增强（Prompt 层已把 hard_rule 写进系统消息）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..world.pools import WorldBible

_NEGATION_HINTS = ("不会", "从不", "绝不", "不可能", "禁止")
_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_ORDER_RE = re.compile(r"(?:第|Day\s*)([0-9]+|[零一二两三四五六七八九十]+)\s*([天日])?", re.IGNORECASE)


def cn_to_int(text: str) -> int:
    """解析「12」「十二」「二十三」这类天数写法。"""
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(text, 0)


@dataclass(slots=True)
class Violation:
    kind: str  # ooc / timeline / world_rule
    severity: str  # warning / blocking
    message: str
    evidence: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence[:200],
            "detail": self.detail,
        }


class ConsistencyChecker:
    """对一段新生成的剧情文本做三类校验。"""

    def __init__(self, world: WorldBible) -> None:
        self.world = world

    # ---- 单角色 OOC ----
    def check_character_ooc(self, sheet: dict[str, Any], text: str) -> list[Violation]:
        violations: list[Violation] = []
        name = str(sheet.get("name", "") or "角色")

        for rule in sheet.get("hard_rule") or []:
            rule_text = str(rule).strip()
            if not rule_text:
                continue
            # 硬性规则若形如「禁止X / 不会X」，只检查 X 的关键词是否出现在同句
            keyword = _extract_rule_keyword(rule_text)
            if keyword and keyword in text:
                violations.append(
                    Violation(
                        kind="ooc",
                        severity="blocking",
                        message=f"{name} 触碰硬性规则：{rule_text}",
                        evidence=_clip_around(text, keyword),
                        detail={"hard_rule": rule_text, "keyword": keyword},
                    )
                )

        speech = str(sheet.get("speech_style", "") or "")
        banned = _banned_words(speech)
        for word in banned:
            if word and word in text:
                violations.append(
                    Violation(
                        kind="ooc",
                        severity="warning",
                        message=f"{name} 使用了禁用词汇：{word}",
                        evidence=_clip_around(text, word),
                        detail={"speech_style": speech},
                    )
                )

        stable = (sheet.get("traits") or {}).get("stable") or []
        for trait in stable:
            opposite = _opposite_of(str(trait))
            if opposite and opposite in text:
                violations.append(
                    Violation(
                        kind="ooc",
                        severity="warning",
                        message=f"{name} 的稳定性格「{trait}」可能被违背",
                        evidence=_clip_around(text, opposite),
                        detail={"trait": trait},
                    )
                )
        return violations

    # ---- 时序 ----
    def check_timeline(
        self,
        text: str,
        *,
        current_day: int = 0,
    ) -> list[Violation]:
        """文本里出现的天数不得小于当前时间线进度。"""
        violations: list[Violation] = []
        for match in _ORDER_RE.finditer(text):
            day = cn_to_int(match.group(1))
            if current_day and day and day < current_day:
                violations.append(
                    Violation(
                        kind="timeline",
                        severity="blocking",
                        message=f"时序倒挂：正文出现第 {day} 天，早于当前进度第 {current_day} 天",
                        evidence=match.group(0),
                        detail={"day": day, "current_day": current_day},
                    )
                )
        return violations

    # ---- 世界观冲突 ----
    def check_world_rules(self, text: str, *, place: str = "") -> list[Violation]:
        violations: list[Violation] = []
        if not place:
            return violations
        try:
            place_record = self.world.map.get(f"loc:{place}") if self.world.map.count() else None
        except Exception:  # noqa: BLE001 - 地点可能尚未入库
            place_record = None
        for forbidden in (place_record or {}).get("forbidden", []) or []:
            token = str(forbidden).strip()
            if token and token in text:
                violations.append(
                    Violation(
                        kind="world_rule",
                        severity="warning",
                        message=f"{place} 的地点规则被触碰：{token}",
                        evidence=_clip_around(text, token),
                        detail={"place": place, "rule": token},
                    )
                )
        return violations

    # ---- 汇总 ----
    def check_all(
        self,
        text: str,
        *,
        characters: list[dict[str, Any]] | None = None,
        current_day: int = 0,
        place: str = "",
    ) -> dict[str, Any]:
        all_violations: list[Violation] = []
        for sheet in characters or []:
            all_violations.extend(self.check_character_ooc(sheet, text))
        all_violations.extend(self.check_timeline(text, current_day=current_day))
        all_violations.extend(self.check_world_rules(text, place=place))

        blocking = [v for v in all_violations if v.severity == "blocking"]
        return {
            "passed": not blocking,
            "blocking_count": len(blocking),
            "warning_count": len(all_violations) - len(blocking),
            "violations": [v.to_public() for v in all_violations],
        }


# ---- 辅助 ----
def _extract_rule_keyword(rule: str) -> str:
    """从「禁止背后偷袭」这类规则里抽出需要盯防的关键词。"""
    cleaned = rule.strip().strip("。；;")
    for hint in _NEGATION_HINTS:
        if hint in cleaned:
            tail = cleaned.split(hint, 1)[1].strip()
            return tail[:8]
    return ""


def _banned_words(speech_style: str) -> list[str]:
    """解析「禁用词汇：A、B」片段。"""
    for sep in ("禁用词汇", "禁用词", "不可使用", "禁词"):
        if sep in speech_style:
            tail = speech_style.split(sep, 1)[1]
            # 去掉紧跟的「汇：」「：」等分隔残留
            tail = re.sub(r"^[^：:]*[：:]", "", tail) if re.search(r"[：:]", tail) else tail
            words = [w.strip() for w in re.split(r"[、,，/|;；\s]", tail) if w.strip()]
            return words[:6]
    return []


_OPPOSITE_MAP = {
    "冷静": ("暴怒", "歇斯底里", "失态"),
    "克制": ("失控", "破口大骂"),
    "忠诚": ("背叛", "出卖"),
    "善良": ("残忍", "虐杀"),
    "果断": ("优柔寡断", "犹豫不决"),
    "谨慎": ("鲁莽", "不计后果"),
}


def _opposite_of(trait: str) -> str:
    for key, opposites in _OPPOSITE_MAP.items():
        if key in trait:
            return opposites[0] if opposites else ""
    return ""


def _clip_around(text: str, token: str, width: int = 30) -> str:
    index = text.find(token)
    if index < 0:
        return ""
    start = max(0, index - width)
    end = min(len(text), index + len(token) + width)
    return text[start:end]
