# 使用手册 · 完整业务流程

对应文档第 6 节四步流程。所有示例都用 MCP 工具调用表示（DSH 里等价于九宫格操作面板）。

---

## 步骤一：初始化配置

### 1.1 配置 API（config.yaml）

```yaml
default_provider: "primary-paid"
use_mock_provider: true          # 无 Key 时兜底，保证链路可跑
providers:
  - name: "primary-paid"
    base_url: "https://api.openai.com/v1"
    api_key: "${SW_KEY_PRIMARY}"  # 启动前 set SW_KEY_PRIMARY=sk-xxx
    model: "gpt-4o-mini"
    tier: "paid"
    priority: 10
    max_concurrency: 3
    rpm: 120
```

- `priority` 越小越先；失败自动降级到下一个，连续失败进入冷却（10s × 失败次数，上限 120s）。
- 免费池写 `tier: "free"` + 较大 `priority` 即可，调度逻辑完全相同。
- 未注入 Key 的 openai 服务商启动时自动 `enabled=false`，`list_providers` 里能看到 `disabled_reason`。

验证：

```
test_provider_connection()                    → 全部服务商连通性
list_providers()                              → 确认 default_provider 与 available
set_provider_quota("free-pool-a", rpm=10)     → 运行期动态限流
```

### 1.2 录入世界观

```
set_mainline_outline(outline="雾港第七日封锁……", timeline=[{"day":7,"event":"潮汐钟停摆"}])
upsert_place("雾港", description="常年有雾的港口城市", rules=["夜间封锁城门"])
upsert_faction("正派小队", description="护送证物的四人小队", allies=["城防军"])
approve_character_card(sheet={...})           # 角色卡见 docs/templates/character_sheet.json
add_ad_hoc_event("密信抵达", "暗流收到布防图", visible_factions=["暗流"], require_approval=False)
```

一键完成：`scripts/init_world.py`（种子数据 + 9 条支线）。

### 1.3 建 9 条支线并绑定九宫格

```
create_narrative_stream("正派小队视角", faction="正派小队", perspective="第三人称限知", cell=1, tags=["faction:正派小队"])
create_narrative_stream("主线大纲",     faction="公共",     cell=5, tags=["plot:主线大纲"])
```

`config.yaml` 的 `streams_preset` 就是这张表，`init_world.py` 会按它批量创建。

### 1.4 接入 DSH

stdio 方式在 `mcp.json` 里加一条（见 README）；SSE 方式直接连 `http://127.0.0.1:8791/sse`。**只配一条 MCP 连接**，九宫格全在这一个窗口内。

---

## 步骤二：自动剧情推演

### 单轮链路

```
触发（冷却结束 / 手动点格）
  → 提取出场角色、地点、势力标签
  → search_by_tags（优先，不命中再 vector_search）
  → filter_by_faction（阵营隔离，secret 受控）
  → 拼装上下文：主线约束 + 角色卡 + 地点规则 + 生效事件 + 最新快照
  → ProviderManager.complete（自动选源、重试、降级）
  → ConsistencyChecker.check_all
      通过 → 追加 content.log + history/dialogue.jsonl，进入下一轮冷却
      冲突 → 不写正文，仅该支线 status=error + last_error，其余支线继续
  → 达阈值 → create_stream_snapshot 生成提案（等人工审批）
```

### DSH 侧调用

```
step_all_due_streams(limit=9)      # 九宫格卡片轮询：每格各自刷新
get_stream_content(stream_id, since_chars=已读长度)  # 只拉增量
```

### 单支线手动步进

```
trigger_stream_step("正派小队视角", hint="让苏晚发现暗渠涨潮", dry_run=True)   # 先预览
trigger_stream_step("正派小队视角", hint="让苏晚发现暗渠涨潮")                # 确认后落盘
```

---

## 步骤三：人工干预操作

| 操作 | 工具 |
| --- | --- |
| 单支线暂停 / 恢复 | `pause_stream` / `resume_stream` |
| 全局冻结 / 继续 | `pause_all_streams` / `resume_all_streams` |
| 插入临时定向事件 | `add_ad_hoc_event(title, content, visible_factions, active_streams, ttl_rounds)` |
| 审核事件 | `list_pending_proposals()` → `decide_proposal(id, approved=True)` |
| 删除事件 | `remove_event(event_id)` |
| 蒸馏角色 | `distill_chat_to_character_sheet("林澈", 对话文本)` → `decide_proposal` |
| 角色版本回滚 | `rollback_character("林澈", 1)` |

事件提案被拒时只留记录，不影响任何支线；审批通过后自动打标签并同步向量库，下一轮剧情即纳入。

---

## 步骤四：长线记忆收拢

```
create_stream_snapshot("正派小队视角")        # 不传 summary → 模型自动压缩
list_snapshots("正派小队视角")                 # 查看 pending
approve_snapshot("正派小队视角", snapshot_id)  # 审批 → 返回裁剪范围
purge_stale_events()                          # 清理 ttl 到期的临时事件
```

审批返回的 `context_policy`：

```json
{ "keep_recent_chars": 1200, "drop_before_chars": 4800, "total_chars": 6100 }
```

下一轮拼装上下文时，只用「最新 2 条快照摘要 + 最近 1200 字原文」，token 总量可控且不断线。

---

## 排错速查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `PROVIDER_UNAVAILABLE` | 全部服务商冷却 / 无 Key / 网络不通 | `list_providers` 看 `last_error` 与 `disabled_reason`；`test_provider_connection` 复查 |
| 支线 `status=error` | 一致性校验 blocking | 看 `last_error` 与 `history/dialogue.jsonl` 的 `warnings`；修 Prompt 或改事件后 `resume_stream` |
| `NOT_FOUND` 支线 | ID/名称写错 | `list_all_streams` 取准确 ID |
| 检索总是 `strategy=vector` | 实体没打标签 | `add_tags(ref, tags, text)` 补索引 |
| 快照不触发 | 未达 `trigger_chars` | 调小 `snapshot.trigger_chars` 或手动 `create_stream_snapshot` |
