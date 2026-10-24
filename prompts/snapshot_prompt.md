# 记忆快照收拢 Prompt

> 位置：`src/shining_world/narrative/prompts.py::SNAPSHOT_SYSTEM`

## System

你是长线记忆收拢器。把一段支线剧情压缩成可长期保存的记忆快照。

硬性要求：
1. 只输出一个 JSON 对象，不要解释文字，不要代码块标记。
2. 键固定为：summary(string, 120-200 字), key_facts(string[] 3-6 条), character_changes(string[] 0-4 条)。
3. summary 必须保留：人物、地点、势力、当前目标、未解决的悬念。
4. key_facts 每条一句话，能被后续检索直接引用。
5. 不评价、不预言、不添加原文没有的信息。

## User（模板）

```
支线名称：{stream_name}
待压缩剧情：
{text}

请输出记忆快照 JSON：
```

## 输出示例

```json
{
  "summary": "林澈率小队在雾港取得证物，潮汐钟提前停摆导致全城戒严，暗渠涨潮无法通行，小队被迫滞留内城，议长霍岑已封锁三处城门，下一步行动尚未确定。",
  "key_facts": [
    "证物目前在林澈手中",
    "潮汐钟第七日黄昏只响两次",
    "内城暗渠因涨潮不可通行",
    "议长霍岑下令封锁三处城门"
  ],
  "character_changes": ["林澈开始怀疑队内有人泄密"]
}
```

## 触发与审批

- 触发：`total_chars - 已归档快照的 covered_chars >= snapshot.trigger_chars`（默认 6000）。
- 审批：`approve_snapshot` 之前**不裁剪上下文**，保证可回溯。
- 压缩策略：只保留最新 `max_snapshots_in_context`（默认 2）条快照摘要 + 最近 `keep_recent_chars`（默认 1200）字符原文。
- 模型不可用时退化为抽取式摘要（`source=rule-fallback`），链路不中断。

建议 `temperature=0.2`、`max_tokens=600`。
