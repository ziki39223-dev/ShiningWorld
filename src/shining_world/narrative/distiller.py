"""角色蒸馏器：对话日志 → 标准角色卡补丁（只出补丁，落库需人工审批）。"""

from __future__ import annotations

import json
import re
from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..common.text import estimate_tokens
from ..providers.provider_manager import ProviderManager
from ..world.character_sheet import merge_character_patch
from .prompts import PromptLibrary

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class CharacterDistiller:
    """调用模型把对话蒸馏成角色卡补丁。"""

    def __init__(self, manager: ProviderManager, prompts: PromptLibrary) -> None:
        self.manager = manager
        self.prompts = prompts

    def distill(
        self,
        character_name: str,
        dialogue: str,
        *,
        base_sheet: dict[str, Any] | None = None,
        max_chars: int = 6000,
    ) -> dict[str, Any]:
        if not character_name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "角色名不能为空")
        if not dialogue.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "对话片段不能为空")

        trimmed = dialogue[-max_chars:]
        result = self.manager.complete(
            [
                {"role": "system", "content": self.prompts.distill_system},
                {"role": "user", "content": self.prompts.distill_user(character_name, trimmed)},
            ],
            temperature=0.3,
            max_tokens=700,
        )

        patch = self._parse_json(result.text)
        patch.setdefault("name", character_name)
        # 规整字段类型，避免模型给出奇怪结构
        patch = _normalize_patch(patch)

        merged = None
        if base_sheet:
            merged = merge_character_patch(base_sheet, patch, source="distill", note="对话蒸馏")

        return {
            "character": character_name,
            "patch": patch,
            "merged_preview": merged,
            "provider": result.provider,
            "model": result.model,
            "dialogue_tokens": estimate_tokens(trimmed),
            "latency_ms": result.latency_ms,
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """容错解析：允许模型带说明文字或 ```json 围栏。"""
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
            candidate = re.sub(r"\s*```$", "", candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(text)
            if not match:
                raise ToolError(
                    ErrorCode.INTERNAL,
                    "蒸馏结果不是合法 JSON",
                    {"raw": text[:400]},
                )
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ToolError(
                    ErrorCode.INTERNAL,
                    "蒸馏结果 JSON 解析失败",
                    {"raw": text[:400], "reason": str(exc)},
                ) from exc
        if not isinstance(data, dict):
            raise ToolError(ErrorCode.INTERNAL, "蒸馏结果必须是 JSON 对象", {"raw": text[:200]})
        return data


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """把模型输出的松散结构压成标准形状。"""
    normalized: dict[str, Any] = {}
    for key in ("name", "identity", "core_belief", "speech_style", "secret"):
        if key in patch:
            normalized[key] = str(patch.get(key) or "").strip()

    traits = patch.get("traits") or {}
    if isinstance(traits, dict):
        normalized["traits"] = {
            "stable": _to_list(traits.get("stable")),
            "temporary": _to_list(traits.get("temporary")),
        }
    elif isinstance(traits, list):
        normalized["traits"] = {"stable": _to_list(traits), "temporary": []}

    for key in ("hard_rule", "tags"):
        if key in patch:
            normalized[key] = _to_list(patch.get(key))

    bonds = patch.get("bond")
    if isinstance(bonds, list):
        normalized["bond"] = [
            {
                "target": str(item.get("target", "")).strip() if isinstance(item, dict) else str(item),
                "relation": str(item.get("relation", "")).strip() if isinstance(item, dict) else "",
                "立场": str(item.get("立场", item.get("stance", ""))).strip()
                if isinstance(item, dict)
                else "",
            }
            for item in bonds
        ]
    return normalized


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[、,，;；\n]", value) if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]
