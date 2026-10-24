# DSH 九宫格主控台配置说明

## 运行形态

- DSH 窗口本身在屏幕居中；**系统桌面不额外开悬浮窗口**。
- DSH 内部一个标准 3×3 网格，9 张支线卡片全部收纳在这一个窗口内。
- 只有一个 MCP 连接：`shining-world`。

## 布局参数

| 项 | 值 |
| --- | --- |
| 布局类型 | 网格 Grid |
| 行列 | 3 行 × 3 列 |
| 卡片宽高 | 等比例均分网格 |
| 网格间隙 | 12 px |
| 对齐 | 网格整体在画布居中 |
| 卡片数量 | 9，一一对应 9 条叙事流 |
| 第 5 格 | 主线，默认浅色高亮边框 |

## 单元格 → 支线绑定

| 格 | 支线 | 阵营 | 视角 |
| --- | --- | --- | --- |
| 1 | 正派小队视角 | 正派小队 | 跟随队长林澈 |
| 2 | 反派议事厅视角 | 反派议事厅 | 议事厅内可见信息 |
| 3 | 中立说书人视角 | 中立 | 俯视全景，只陈述已发生事实 |
| 4 | 密探/信使视角 | 密探网 | 单线跟随，信息受限于信件内容 |
| **5** | **主线大纲** | 公共 | 主线推进，默认高亮 |
| 6 | 暗流伏笔线 | 暗流 | 幕后视角，只露线索不揭底 |
| 7 | 守卫/城防视角 | 城防军 | 城墙视角，关注出入城与布防 |
| 8 | 隐士/旅人视角 | 旅人 | 游走视角，串地理与传说 |
| 9 | 边疆战事视角 | 边疆军 | 战场视角，节奏更快 |

## 每格卡片字段

```
支线名称         ← manifest.name
状态标签         ← status: 冷却中 / 运行中 / 暂停 / OOC告警
剧情滚动文本     ← get_stream_content(stream_id, since_chars)
cooldown_remaining_s   ← 剩余冷却秒数（进度条 / 倒计时）
step_count / total_chars ← 累计推进轮数与字数
last_error       ← 告警原因（status=error 时显示）
```

## 轮询与刷新

```
每 3–5 秒：
  step_all_due_streams(limit=9)     # 到期支线各推进一步
  for 每张卡片:
      get_stream_content(stream_id, since_chars=卡片已读长度, limit_chars=2000)
      追加渲染，按返回的 has_more 决定是否继续拉
```

各格**独立冷却计时器、独立增量追加**，错落刷新，互不锁死。

## 单格交互

| 点击 | 调用 |
| --- | --- |
| 暂停 | `pause_stream(stream_id)` |
| 恢复 | `resume_stream(stream_id)` |
| 手动步进 | `trigger_stream_step(stream_id, hint)` |
| 插入临时事件 | `add_ad_hoc_event(...)` |
| 蒸馏角色快照 | `distill_chat_to_character_sheet(name, dialogue)` |
| 查看告警 | 读 `last_error` + `list_pending_proposals()` |

## 冲突处理约定

任一格校验冲突（OOC / 时序 / 设定冲突）时：

- 只有该格变红并弹出告警，`status=error`，`last_error` 写明原因；
- 其余 8 格继续正常运行，全局不停摆；
- 处理完（改 Prompt / 修事件 / 改角色卡）后 `resume_stream` 恢复。

## 顶栏建议布局

```
[全局暂停] [全局继续] [待审提案 N] [默认模型源 ▾] [服务状态]
```

- 待审提案数 = `get_service_status().pending_proposals`
- 默认模型源 = `switch_default_provider(name)`
- 服务状态 = `get_service_status()` + `list_providers()` 的 `available` 计数
