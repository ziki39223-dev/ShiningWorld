"""一键初始化工作区：录入世界观种子数据 + 按 config.yaml 的 streams_preset 建 9 条支线。

用法：
    .venv/Scripts/python.exe scripts/init_world.py --config config.yaml
    .venv/Scripts/python.exe scripts/init_world.py --config config.yaml --force   # 覆盖已有支线
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shining_world.config.loader import load_settings  # noqa: E402
from shining_world.tools.bootstrap import build_service_from_settings, persist_indexes  # noqa: E402
from shining_world.world.character_sheet import build_character_sheet  # noqa: E402

SEED_PLACES = [
    {"name": "雾港", "description": "常年被雾笼罩的港口城市，三方势力交汇。", "faction": "", "rules": ["夜间封锁城门", "外船不得靠岸"]},
    {"name": "潮汐钟楼", "description": "内城最高处，钟声可传十里。", "faction": "城防军", "rules": ["非守军不得登顶"]},
    {"name": "内城暗渠", "description": "排水暗渠，可绕开城门。", "faction": "暗流", "rules": ["涨潮时不可通行"]},
]

SEED_FACTIONS = [
    {"name": "正派小队", "description": "护送证物的四人小队，目标是把证物送出城。", "stance": "lawful", "allies": ["城防军"], "enemies": ["反派议事厅"]},
    {"name": "反派议事厅", "description": "掌握内城兵权的议会长老团，想要潮汐钟。", "stance": "hostile", "allies": [], "enemies": ["正派小队"]},
    {"name": "暗流", "description": "游走于各方的情报网络，只卖消息不站队。", "stance": "neutral", "allies": [], "enemies": []},
    {"name": "城防军", "description": "负责城门与城墙防务，立场摇摆。", "stance": "neutral", "allies": ["正派小队"], "enemies": []},
]

SEED_CHARACTERS = [
    {
        "name": "林澈",
        "identity": "正派小队队长",
        "core_belief": "不带任何人掉队",
        "traits": {"stable": ["冷静", "谨慎"], "temporary": []},
        "speech_style": "简短克制；禁用词汇：混蛋、去死",
        "bond": [{"target": "苏晚", "relation": "队友", "立场": "守护"}],
        "secret": "他曾在议事厅当过三年暗桩",
        "secret_visible_to": ["暗流"],
        "hard_rule": ["禁止背后偷袭", "禁止抛弃队友"],
        "tags": ["char:林澈", "faction:正派小队"],
        "faction": "正派小队",
    },
    {
        "name": "苏晚",
        "identity": "小队斥候",
        "core_belief": "情报比刀快",
        "traits": {"stable": ["敏锐", "多疑"], "temporary": []},
        "speech_style": "语速快，爱用反问",
        "bond": [{"target": "林澈", "relation": "队长", "立场": "信任但保留"}],
        "secret": "",
        "hard_rule": ["禁止向敌对阵营透露小队路线"],
        "tags": ["char:苏晚", "faction:正派小队"],
        "faction": "正派小队",
    },
    {
        "name": "议长霍岑",
        "identity": "反派议事厅议长",
        "core_belief": "秩序高于一切代价",
        "traits": {"stable": ["克制", "冷酷"], "temporary": []},
        "speech_style": "缓慢、句式工整",
        "bond": [],
        "secret": "潮汐钟其实早已损坏，他要的是消息不外泄",
        "secret_visible_to": ["反派议事厅"],
        "hard_rule": ["禁止在公开场合失态"],
        "tags": ["char:议长霍岑", "faction:反派议事厅"],
        "faction": "反派议事厅",
    },
]

SEED_EVENTS = [
    {
        "title": "潮汐钟停摆",
        "content": "第七日黄昏钟声只响两次，全城进入戒严。",
        "visible_factions": [],
        "active_streams": [],
        "tags": ["event:潮汐钟停摆"],
        "ttl_rounds": 0,
    },
    {
        "title": "密信抵达",
        "content": "暗流收到内城布防图，要价极高。",
        "visible_factions": ["暗流", "正派小队"],
        "active_streams": [],
        "tags": ["event:密信抵达"],
        "ttl_rounds": 3,
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="初始化闪亮大世界工作区")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--force", action="store_true", help="已存在同名支线时跳过（默认）或忽略")
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    service = build_service_from_settings(settings)

    if not service.world.plot.mainline():
        service.world.plot.set_mainline_outline(settings.mainline_outline)

    created = {"places": 0, "factions": 0, "characters": 0, "events": 0, "streams": 0}

    existing_places = {item.get("name") for item in service.world.map.list()}
    for place in SEED_PLACES:
        if place["name"] in existing_places:
            continue
        service.world.map.upsert_place(
            place["name"],
            description=place["description"],
            faction=place["faction"],
            rules=place["rules"],
            tags=[f"loc:{place['name']}"],
        )
        created["places"] += 1

    existing_factions = {item.get("name") for item in service.world.culture.list()}
    for faction in SEED_FACTIONS:
        if faction["name"] in existing_factions:
            continue
        service.world.culture.upsert_faction(
            faction["name"],
            description=faction["description"],
            stance=faction["stance"],
            allies=faction["allies"],
            enemies=faction["enemies"],
            tags=[f"faction:{faction['name']}"],
        )
        created["factions"] += 1

    existing_chars = {item.get("name") for item in service.world.character.list()}
    for character in SEED_CHARACTERS:
        if character["name"] in existing_chars:
            continue
        sheet = build_character_sheet(character, source="seed")
        sheet["faction"] = character["faction"]
        service.world.character.approve_card(sheet)
        created["characters"] += 1

    existing_events = {item.get("title") for item in service.world.plot.list_events()}
    for event in SEED_EVENTS:
        if event["title"] in existing_events:
            continue
        service.world.plot.add_event(
            event["title"],
            event["content"],
            visible_factions=event["visible_factions"],
            active_streams=event["active_streams"],
            tags=event["tags"],
            ttl_rounds=event["ttl_rounds"],
        )
        created["events"] += 1

    existing_streams = {record.name for record in service.streams.list()}
    for preset in settings.streams_preset:
        if preset["name"] in existing_streams:
            continue
        service.streams.create(
            str(preset["name"]),
            faction=str(preset.get("faction", "")),
            perspective=str(preset.get("perspective", "")),
            cooldown_s=settings.stream_defaults.cooldown_s,
            tags=list(preset.get("tags") or []),
            cell=int(preset.get("cell", 0)),
        )
        created["streams"] += 1

    persist_indexes(service)

    summary = {
        "workspace": str(settings.workspace_root),
        "created": created,
        "totals": service.stats(),
        "streams": [
            {"cell": r.cell, "name": r.name, "status": r.status, "id": r.stream_id}
            for r in service.streams.list()
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
