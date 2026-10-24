"""本地 Mock 服务商：无 API Key 时也能跑通全链路（联调 / 单测）。"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from .base import ChatMessage, Provider


class MockProvider(Provider):
    """确定性伪随机文本生成，保证同输入同输出，便于测试断言。

    当系统提示要求输出 JSON（蒸馏 / 快照）时，改为返回合法 JSON，
    这样离线状态下也能完整演示「蒸馏 → 审批 → 归档」链路。
    """

    def __init__(self, name: str = "mock-local", model: str = "mock-1") -> None:
        self.name = name
        self.model = model
        self._calls = 0

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.85,
        max_tokens: int = 800,
    ) -> str:
        self._calls += 1
        system = "\n".join(m.content for m in messages if m.role == "system")
        prompt = "\n".join(m.content for m in messages if m.role != "system")
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        rng = random.Random(int(digest[:8], 16))

        if "JSON" in system:
            return _mock_json(system, prompt, rng)

        faction = _guess(prompt, "阵营") or "无名势力"
        place = _guess(prompt, "地点") or "边境小镇"
        cast = _guess(prompt, "出场角色") or "无名旅人"

        beats = [
            f"{place}的灯在夜风里晃了一下，{cast}停住脚步。",
            f"{faction}的人从巷口走出来，没有人先开口。",
            f"{cast}把手按在身侧，指节泛白，却只是笑了一下。",
            f"远处传来钟声，{place}的秩序在这一刻松动了一寸。",
            f"{faction}留下了半句话，剩下的意思要等到明天。",
            f"{cast}转身时，雨已经落下来了。",
        ]
        rng.shuffle(beats)
        chosen = beats[: 3 + self._calls % 2]
        text = "".join(chosen)
        budget = max(60, min(max_tokens * 2, 400))
        return text[:budget]

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": True, "sample": "mock ready", "calls": self._calls}


def _mock_json(system: str, prompt: str, rng: random.Random) -> str:
    """按 Prompt 意图生成结构化 JSON。"""
    name = _guess(prompt, "角色名") or _guess(prompt, "支线名称") or "无名角色"
    if "快照" in system:
        facts = [
            f"{name}完成了一轮推进。",
            "关键人物仍在场上。",
            "悬念尚未揭晓。",
        ]
        rng.shuffle(facts)
        return json.dumps(
            {
                "summary": f"{name}本轮推进结束：局势收紧，主要人物均已登场，下一步行动尚未展开。",
                "key_facts": facts[:3],
                "character_changes": [],
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "name": name,
            "identity": "在场行动者",
            "core_belief": "把事情做完",
            "traits": {"stable": ["克制"], "temporary": []},
            "speech_style": "简短",
            "bond": [],
            "secret": "",
            "hard_rule": [f"{name}不得背弃同行者"],
            "tags": [],
        },
        ensure_ascii=False,
    )


def _guess(prompt: str, label: str) -> str:
    """从上下文中提取 ``标签：值`` 形式的字段，取第一行。"""
    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith(label):
            for sep in ("：", ":"):
                if sep in line:
                    return line.split(sep, 1)[1].strip().strip("，。；")
    return ""
