# 标签使用规范

## 六个合法前缀

| 前缀 | 用途 | 示例 |
| --- | --- | --- |
| `char:` | 角色 | `char:林澈` |
| `loc:` | 地点 | `loc:雾港` |
| `faction:` | 势力 / 阵营 | `faction:正派小队` |
| `event:` | 事件 ID | `event:event_a1b2c3d4e5f6` |
| `plot:` | 剧情段落 | `plot:主线大纲` |
| `rule:` | 世界观规则 | `rule:夜间封城` |

格式约束（代码强制校验，违反直接 `INVALID_ARGUMENT`）：

- 必须含且仅含一个冒号，前缀必须在上述六项内；
- 冒号后长度 1–64，不含空白与冒号；
- 同一实体重复打同一标签自动去重。

## 命名约定

1. **实体名即标签名**：`loc:雾港` 对应地图池 `loc:雾港` 记录，二者必须一致，否则检索召回后取不到正文。
2. **阵营标签用全称**：`faction:正派小队`，不要写 `faction:正派`，否则阵营过滤（`filter_by_faction`）会漏。
3. **事件标签用事件 ID**：`event:` 后跟入库返回的 `id`，不要用标题，标题会改。
4. **剧情段落用语义短名**：`plot:主线大纲` / `plot:第一卷·雾港封锁`。
5. **规则标签写约束本身**：`rule:夜间封城`，便于规则类召回。

## 打标签的时机

| 时机 | 谁来做 |
| --- | --- |
| 录入地点 / 势力 / 角色卡 | 各 `upsert_*` / `approve_character_card` 自动打默认标签 |
| 插入事件 | `add_ad_hoc_event` 自动打 `event:<id>` |
| 补标 / 纠错 | `add_tags(ref, tags, text, faction)` |
| 下线 | `remove_tags(ref, tags)`，标签清空后实体自动移出索引 |

## 检索策略

```
search_by_tags(tags, match_all=True)   # 交集：精确锁定（默认、优先）
search_by_tags(tags, match_all=False)  # 并集：放宽召回
vector_search(query)                   # 仅在标签命中 < vector_fallback_min_tag_hits 时兜底
```

- **永远先标签**：`ContextBuilder.build()` 内部就是先 `search_by_tags`（`match_all=False`），命中数不足才向量。
- **向量只兜底**：标签命中 ≥ 阈值时不走向量，保证设定稳定、结果可复现。
- **阵营隔离在最后一道**：`faction_scope` 过滤发生在两种检索之后，`meta.faction` 为空视为公共内容。

## 反例

| 写法 | 问题 |
| --- | --- |
| `林澈` | 缺前缀，无法判断实体类型 |
| `char:` | 空名 |
| `char:林 澈` | 含空格，格式非法 |
| `npc:张三` | 前缀不在白名单 |
| `char:队长` | 用了称号而非姓名，`get_character` 取不到 |
| `faction:正派` | 与实体全称不一致，阵营过滤漏项 |
