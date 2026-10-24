"""三套核心 Prompt：剧情推演 / 角色蒸馏 / 快照收拢。

放在代码里（而非只放文件）是为了让服务即使没有 prompts/ 目录也能跑；
``prompts/*.md`` 是给人改的副本，两者以代码为唯一事实来源。
"""

from __future__ import annotations

from dataclasses import dataclass

STORY_SYSTEM = """你是《闪亮大世界》的群像剧情推演引擎，负责为指定叙事支线续写一小段剧情。

硬性要求：
1. 只输出剧情正文，不要标题、不要解释、不要 Markdown 标记。
2. 篇幅控制在 150-320 字，一到三个自然段，落在一个可收束的行动节拍上。
3. 严格遵守下方「主线约束」「角色硬性规则」「地点规则」，任何冲突都不允许出现。
4. 只能使用「本轮可用素材」中出现过的角色、地点、势力；不得凭空创造新阵营的重要人物。
5. 视角固定为该支线视角，不得描写该视角无法感知的信息（信息隔离）。
6. 不写总结陈词，不做时间跳跃，不复述前情。"""

DISTILL_SYSTEM = """你是角色蒸馏器。从给定的对话片段中提炼该角色的标准化角色卡补丁。

硬性要求：
1. 只输出一个 JSON 对象，不要任何解释文字，不要 ```json 代码块标记。
2. 允许出现的键：name, identity, core_belief, traits{stable[], temporary[]}, speech_style, bond[{target,relation,立场}], secret, hard_rule[], tags[]。
3. traits.stable 与 hard_rule 只写对话中有明确证据的；证据不足就留空数组。
4. tags 使用规范前缀：char: / loc: / faction: / event: / plot: / rule:。
5. 不得输出 char_id、evolution_log。"""

SNAPSHOT_SYSTEM = """你是长线记忆收拢器。把一段支线剧情压缩成可长期保存的记忆快照。

硬性要求：
1. 只输出一个 JSON 对象，不要解释文字，不要代码块标记。
2. 键固定为：summary(string, 120-200 字), key_facts(string[] 3-6 条), character_changes(string[] 0-4 条)。
3. summary 必须保留：人物、地点、势力、当前目标、未解决的悬念。
4. key_facts 每条一句话，能被后续检索直接引用。
5. 不评价、不预言、不添加原文没有的信息。"""


@dataclass(slots=True)
class PromptLibrary:
    """Prompt 集合。"""

    story_system: str = STORY_SYSTEM
    distill_system: str = DISTILL_SYSTEM
    snapshot_system: str = SNAPSHOT_SYSTEM

    def story_user(self, context_block: str) -> str:
        return f"{context_block}\n\n请按上述约束续写本支线下一段剧情："

    def distill_user(self, character_name: str, dialogue: str) -> str:
        return (
            f"角色名：{character_name}\n"
            f"对话片段：\n{dialogue}\n\n"
            "请输出该角色的角色卡补丁 JSON："
        )

    def snapshot_user(self, stream_name: str, text: str) -> str:
        return (
            f"支线名称：{stream_name}\n"
            f"待压缩剧情：\n{text}\n\n"
            "请输出记忆快照 JSON："
        )
