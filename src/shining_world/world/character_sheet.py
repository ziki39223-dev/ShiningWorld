"""角色卡：固定模板 + 校验 + 蒸馏结果规整。

模板字段严格对应文档 5.4.3，任何新增字段都要在此同步，保证跨支线一致。
"""

from __future__ import annotations

from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..common.ids import new_id, now_iso

CHARACTER_SHEET_TEMPLATE: dict[str, Any] = {
    "char_id": "",
    "name": "",
    "identity": "",
    "core_belief": "",
    "traits": {"stable": [], "temporary": []},
    "speech_style": "",
    "bond": [],
    "secret": "",
    "secret_visible_to": [],
    "evolution_log": [],
    "hard_rule": [],
    "tags": [],
}

REQUIRED_FIELDS = ("name", "identity", "core_belief", "hard_rule")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("；", ";").split(";")]
        return [p for p in parts if p]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def validate_character_sheet(sheet: dict[str, Any]) -> list[str]:
    """返回问题清单（空列表表示通过）。"""
    problems: list[str] = []
    if not isinstance(sheet, dict):
        return ["角色卡必须是 JSON 对象"]
    for field in REQUIRED_FIELDS:
        if not str(sheet.get(field, "") or "").strip():
            problems.append(f"缺少必填字段：{field}")
    traits = sheet.get("traits")
    if not isinstance(traits, dict):
        problems.append("traits 必须是 {stable: [], temporary: []} 结构")
    else:
        if not _as_list(traits.get("stable")):
            problems.append("traits.stable 不能为空（底层性格是防 OOC 的底线）")
        if not isinstance(traits.get("temporary", []), list):
            problems.append("traits.temporary 必须是数组")
    if not _as_list(sheet.get("hard_rule")):
        problems.append("hard_rule 不能为空（禁止 OOC 的硬性规则）")
    bond = sheet.get("bond")
    if bond is not None and not isinstance(bond, list):
        problems.append("bond 必须是数组")
    return problems


def build_character_sheet(raw: dict[str, Any], *, source: str = "manual") -> dict[str, Any]:
    """把任意来源（人工 / 蒸馏）的原始数据规整成标准角色卡。"""
    if not isinstance(raw, dict):
        raise ToolError(ErrorCode.INVALID_ARGUMENT, "角色卡原始数据必须是 JSON 对象")

    name = str(raw.get("name", "") or "").strip()
    if not name:
        raise ToolError(ErrorCode.INVALID_ARGUMENT, "角色卡缺少 name")

    traits_raw = raw.get("traits") or {}
    if not isinstance(traits_raw, dict):
        traits_raw = {"stable": _as_list(traits_raw)}

    bonds: list[dict[str, str]] = []
    for item in raw.get("bond") or []:
        if isinstance(item, dict):
            bonds.append(
                {
                    "target": str(item.get("target", "") or ""),
                    "relation": str(item.get("relation", "") or ""),
                    "立场": str(item.get("立场", item.get("stance", "")) or ""),
                }
            )
        elif isinstance(item, str) and item.strip():
            bonds.append({"target": item.strip(), "relation": "", "立场": ""})

    sheet: dict[str, Any] = {
        "char_id": str(raw.get("char_id") or new_id("char")),
        "name": name,
        "identity": str(raw.get("identity", "") or "").strip(),
        "core_belief": str(raw.get("core_belief", "") or "").strip(),
        "traits": {
            "stable": _as_list(traits_raw.get("stable")),
            "temporary": _as_list(traits_raw.get("temporary")),
        },
        "speech_style": str(raw.get("speech_style", "") or "").strip(),
        "bond": bonds,
        "secret": str(raw.get("secret", "") or "").strip(),
        "secret_visible_to": _as_list(raw.get("secret_visible_to")),
        "evolution_log": list(raw.get("evolution_log") or []),
        "hard_rule": _as_list(raw.get("hard_rule")),
        "tags": _as_list(raw.get("tags")),
    }
    sheet["evolution_log"].append(
        {"at": now_iso(), "source": source, "note": str(raw.get("note", "") or "创建角色卡")}
    )
    return sheet


def merge_character_patch(
    sheet: dict[str, Any],
    patch: dict[str, Any],
    *,
    source: str = "distill",
    note: str = "",
) -> dict[str, Any]:
    """把蒸馏出的增量补丁合并进角色卡；stable / hard_rule 只增不减。"""
    merged = dict(sheet)
    for key, value in patch.items():
        if key in {"char_id", "evolution_log", "traits", "hard_rule", "tags", "bond"}:
            continue
        if value not in (None, "", []):
            merged[key] = value

    traits_patch = patch.get("traits") or {}
    if isinstance(traits_patch, dict):
        traits = dict(merged.get("traits") or {})
        stable = list(traits.get("stable", []))
        for item in _as_list(traits_patch.get("stable")):
            if item not in stable:
                stable.append(item)
        traits["stable"] = stable
        traits["temporary"] = _as_list(traits_patch.get("temporary")) or list(
            traits.get("temporary", [])
        )
        merged["traits"] = traits

    for field in ("hard_rule", "tags"):
        current = list(merged.get(field, []))
        for item in _as_list(patch.get(field)):
            if item not in current:
                current.append(item)
        merged[field] = current

    bonds = list(merged.get("bond", []))
    for item in patch.get("bond") or []:
        if isinstance(item, dict):
            target = str(item.get("target", "") or "")
            existing = next((b for b in bonds if b.get("target") == target), None)
            if existing is None:
                bonds.append(
                    {
                        "target": target,
                        "relation": str(item.get("relation", "") or ""),
                        "立场": str(item.get("立场", item.get("stance", "")) or ""),
                    }
                )
            else:
                for key in ("relation", "立场"):
                    if item.get(key):
                        existing[key] = str(item[key])
    merged["bond"] = bonds

    log = list(merged.get("evolution_log", []))
    log.append({"at": now_iso(), "source": source, "note": note or "蒸馏补丁"})
    merged["evolution_log"] = log
    return merged
