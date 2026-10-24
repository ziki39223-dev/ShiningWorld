# MCP 工具全集

服务名：`shining-world` · 版本：1.0.0 · 共 **45** 个工具。

所有工具返回统一信封：

```json
{ "ok": true,  "...": "业务字段" }
{ "ok": false, "error": { "code": "NOT_FOUND", "message": "...", "detail": {} } }
```

错误码：`INVALID_ARGUMENT` / `NOT_FOUND` / `CONFLICT` / `PROVIDER_UNAVAILABLE` / `PERMISSION_DENIED` / `CONSISTENCY_VIOLATION` / `IO_ERROR` / `INTERNAL`。

---

## 一、系统（1）

### `get_service_status`
无参数。返回工作区路径、支线数、世界观统计、默认服务商、待审提案数。

```json
{ "ok": true, "workspace": "E:\\dd\\ShiningWorld", "streams": 9,
  "world": { "plot_events": 3, "places": 3, "factions": 4, "characters": 3,
             "pending_proposals": 0, "vector_rows": 10, "tags": 12 },
  "default_provider": "primary-paid", "pending_proposals": 0 }
```

---

## 二、模型服务商管理（4）

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_providers` | — | 全部服务商 + 运行时状态（active / calls / failures / available / cooldown_s_left / last_error / disabled_reason） |
| `switch_default_provider` | `name` | 切换全局默认模型源 |
| `set_provider_quota` | `name`, `max_concurrency?`, `rpm?` | 并发与每分钟上限，两者至少给一个 |
| `test_provider_connection` | `name?` | 连通性测试；不传则测全部 |

未注入 API Key 的 openai 类服务商启动时自动 `enabled=false` 并给出 `disabled_reason`，不会每次调用都白跑一次失败。

---

## 三、叙事流管理器（9）

| 工具 | 关键参数 | 说明 |
| --- | --- | --- |
| `create_narrative_stream` | `name`, `faction?`, `perspective?`, `cooldown_s?`, `tags?`, `cell?` | 建支线，`cell=1..9`，5 为主线 |
| `trigger_stream_step` | `stream_id`, `hint?`, `dry_run?`, `max_tokens?` | 单支线步进：检索 → 生成 → 校验 → 落盘 |
| `step_all_due_streams` | `limit?`（默认 9） | 所有冷却结束的支线各推进一步 |
| `get_stream_content` | `stream_id`, `since_chars?`, `limit_chars?` | 增量读取正文（DSH 卡片刷新） |
| `list_all_streams` | — | 全部支线状态与累计字数 |
| `pause_stream` / `resume_stream` | `stream_id` | 单支线暂停 / 恢复 |
| `pause_all_streams` / `resume_all_streams` | — | 全局冻结 / 继续 |

`trigger_stream_step` 返回：

```json
{ "ok": true, "result": {
  "stream_id": "s_18894bfdefee", "stream_name": "正派小队视角",
  "text": "……", "provider": "primary-paid", "model": "gpt-4o-mini",
  "latency_ms": 1830, "attempts": 1,
  "check": { "passed": true, "blocking_count": 0, "warning_count": 0, "violations": [] },
  "context": { "characters": ["林澈"], "places": ["雾港"], "events": ["潮汐钟停摆"],
               "retrieval_strategy": "tag", "retrieval_hits": 3 },
  "paused": false, "snapshot_proposal": null, "dry_run": false } }
```

一致性校验出现 blocking 违规时：**不写入正文**，该支线置 `status=error` 并记录 `last_error`，其他支线不受影响。

---

## 四、检索引擎（5）

标签前缀规范：`char:` / `loc:` / `faction:` / `event:` / `plot:` / `rule:`。非法前缀或格式直接 `INVALID_ARGUMENT`。

| 工具 | 关键参数 | 说明 |
| --- | --- | --- |
| `add_tags` | `ref`, `tags`, `text?`, `faction?` | 打标签；带 `text` 时同步写向量库 |
| `remove_tags` | `ref`, `tags` | 删标签，清空后实体移出索引 |
| `search_by_tags` | `tags`, `match_all?`（默认 true=交集）, `faction?`, `limit?` | 纯标签精确检索，不走向量 |
| `vector_search` | `query`, `top_k?`, `faction?` | 语义召回（仅兜底用） |
| `filter_by_faction` | `faction`, `refs?` | 返回 `visible` / `hidden` 两组，实现阵营隔离 |

检索策略判定：标签命中 ≥ `retrieval.vector_fallback_min_tag_hits`（默认 1）时**不**启动向量，`strategy` 为 `tag`；否则为 `vector` 或 `tag+vector`。

---

## 五、世界观池子与审批（18）

### 剧情池

| 工具 | 关键参数 |
| --- | --- |
| `set_mainline_outline` | `outline`, `timeline?` |
| `add_ad_hoc_event` | `title`, `content`, `visible_factions?`, `active_streams?`, `tags?`, `ttl_rounds?`, `require_approval?`（默认 true） |
| `list_events` | `faction?`, `stream_id?` |
| `remove_event` | `event_id` |

### 地图池 / 人文池

| 工具 | 关键参数 |
| --- | --- |
| `upsert_place` | `name`, `description?`, `faction?`, `rules?`, `tags?` |
| `list_places` | `faction?`（空归属视为公共，始终可见） |
| `get_place` | `name` |
| `remove_place` | `name`（同步撤下标签索引与向量库） |
| `upsert_faction` | `name`, `description?`, `stance?`, `allies?`, `enemies?`, `tags?` |
| `list_factions` | — |
| `get_faction` | `name` |
| `remove_faction` | `name`（同步撤下标签索引与向量库） |

### 人物池（角色蒸馏核心）

| 工具 | 关键参数 |
| --- | --- |
| `distill_chat_to_character_sheet` | `character_name`, `dialogue`, `base_character?`, `auto_submit?` |
| `approve_character_card` | `sheet`, `note?`, `approved_by?` |
| `get_character` | `name_or_id`, `viewer_faction?` |
| `rollback_character` | `name_or_id`, `version` |

角色卡固定模板（`docs/templates/character_sheet.json`）：

```json
{
  "char_id": "char_xxx", "name": "", "identity": "", "core_belief": "",
  "traits": { "stable": [], "temporary": [] },
  "speech_style": "", "bond": [{ "target": "", "relation": "", "立场": "" }],
  "secret": "", "secret_visible_to": [],
  "evolution_log": [], "hard_rule": [], "tags": []
}
```

必填：`name` / `identity` / `core_belief` / `traits.stable` / `hard_rule`。同名角色再次归档 = 生成新版本，历史保留 20 版。

### 提案审批

| 工具 | 关键参数 |
| --- | --- |
| `list_pending_proposals` | `status?`（pending / approved / rejected / failed） |
| `decide_proposal` | `proposal_id`, `approved?`, `note?` |

提案落库失败时状态置 `failed` 并保留原因，不影响其他提案。

---

## 六、快照记忆（4）

| 工具 | 关键参数 | 说明 |
| --- | --- | --- |
| `create_stream_snapshot` | `stream_id`, `summary?`, `key_facts?`, `source?` | 不传 `summary` 则调模型压缩 |
| `approve_snapshot` | `stream_id`, `snapshot_id`, `note?` | 归档并返回 `context_policy.drop_before_chars` |
| `list_snapshots` | `stream_id` | 全部快照与状态 |
| `purge_stale_events` | — | 清理 `ttl_rounds` 到期的临时事件 |

快照未被批准前**不裁剪上下文**；`buildMemoryContext` 只取已批准的最新 N 条快照 + 最近 `keep_recent_chars` 字符。

---

## 七、一致性校验（4）

| 工具 | 关键参数 | 拦截内容 |
| --- | --- | --- |
| `check_character_ooc` | `character`, `text`, `viewer_faction?` | `hard_rule` 关键词越线（blocking）、禁用词（warning）、稳定性格反义（warning） |
| `check_timeline_conflict` | `text`, `current_day?` | 正文天数早于进度（blocking），支持「十二」「23」两种写法 |
| `check_world_rule_conflict` | `text`, `place?` | 地点 `forbidden` 规则越线（warning） |
| `pause_stream_on_error` | `stream_id`, `reason?` | 冻结指定支线，`affected_others` 恒为空 |

校验全部为确定性规则，**不消耗模型额度**。
