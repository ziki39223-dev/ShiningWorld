title: 源文档解读工作简报（闪亮大世界_项目终极清单_V1.0.docx）
as_of: 2026-10-22
source: C:\Users\haibol\AppData\Roaming\AIWorkspace\config\temp\闪亮大世界_项目终极清单_V1.0.docx（47,421 字节，V1.0 定稿，定稿日期 2026年10月22日）
extract_method: officecli view <file> text（仅作结构抽取，未用其他解析器）

## 一、文档骨架（10 章，213 段）

1. 文档信息（项目定位、接入方案、工作台）
2. 总体方案：2.1 顶层链路（固定不变）· 2.2 核心约束（不可改动）· 2.3 架构模块清单（全部保留，8 项）
3. 九宫格主控台布局：3.1 布局方案 · 3.2 单元格分配（9 格逐格定义）· 3.3 布局参数 · 3.4 交互表现
4. 目录结构（shining-world/ 树形清单）
5. MCP 工具全集：5.1 服务商管理 · 5.2 叙事流管理 · 5.3 检索 · 5.4 世界观池子（剧情/地图/人文/人物 + 审批）· 5.5 快照记忆 · 5.6 一致性校验
6. 完整业务流程：6.1 初始化配置 · 6.2 自动推演 · 6.3 人工干预 · 6.4 长线记忆收拢
7. 分阶段开发排期：阶段一～阶段六（各带「交付成果」）
8. 本方案核心优势（7 条）
9. 配套文件清单（config 样板、3 套 Prompt、面板配置、角色卡/事件模板、标签规范）
10. 风险控制清单（5 条）

## 二、不可改动的硬约束（实现必须逐条对齐）

- 固定链路：DSH 工作台 →(MCP stdio/SSE)→ 自研调度服务 → 模型适配器层 → 多家 OpenAI 兼容 API（付费 + 免费池）。
- 不接 Trae / Qoder / WorkBuddy CLI 与第三方 MCP；无子进程、无账号轮换、无 CLI 会话管理。
- 检索：标签精确检索优先，向量检索兜底。
- 记忆：分段快照归档 + 人工审批，压缩上下文。
- 世界观变更：全部走提案 + 人工审批，防吃书。
- 多支线隔离：独立视角、独立阵营、独立冷却；单支线暂停不影响全局。
- 工作台固定 DSH，仅一条 MCP 连接；九宫格共 9 张卡片全收在一个窗口内，桌面不加悬浮窗。

## 三、九宫格格位（3×3，间隙 12px，第 5 格主线高亮）

1 正派小队 / 2 反派议事厅 / 3 中立说书人 / 4 密探·信使 / **5 主线大纲（高亮）** / 6 暗流伏笔 / 7 守卫·城防 / 8 隐士·旅人 / 9 边疆战事。

## 四、交付映射（文档要求 → 本仓库落地）

| 文档章节 | 落地位置 |
| --- | --- |
| 2.1 顶层链路 | `docs/architecture.md` 层 1；`src/shining_world/server/app.py` 指令串 |
| 2.2 核心约束 | 代码层强制：`providers/`（无 CLI）、`retrieval/engine.py`（标签优先）、`streams/`（独立状态机）、`world/`（提案审批） |
| 2.3 架构模块清单 | `providers/` `streams/` `retrieval/` `world/` `narrative/distiller.py` `streams/snapshot.py` `consistency/` 一一对应 |
| 3 九宫格 | `config.yaml::streams_preset`；`docs/dsh-panel.md`；`scripts/init_world.py` 批量建格 |
| 4 目录结构 | `config.yaml` + `providers/` + `world-bible/{plot,map,culture,character}/index.json` + `vector_db/` + `streams/stream-{id}-{faction}/` + `logs/` |
| 5.x MCP 工具 | `server/app.py` 注册 **39** 个工具，签名见 `docs/mcp-tools.md` |
| 6 业务流程 | `docs/usage.md` 四步流程逐步对应工具调用 |
| 7 分阶段排期 | 阶段一～六已一次性实现（含自检与 E2E），见下「验证」 |
| 9 配套文件 | `config.yaml`、`prompts/{story,distill,snapshot}_prompt.md`、`docs/dsh-panel.md`、`docs/templates/*.json`、`docs/tag-spec.md` |
| 10 风险控制 | 限流（provider quota + 冷却）、上下文爆炸（快照阈值）、人设崩坏（hard_rule + 自动校验 + 人工审批）、吃书（提案 + 版本回滚）、支线失控（独立状态机） |

## 五、验证证据（本轮实跑）

- 单元测试：`pytest -q` → **80 passed**（retrieval / providers / streams / world / consistency / narrative / tools 七个文件）。
- 离线自检：`python -m shining_world selfcheck` → **8/8 OK**（临时目录跑，不污染工作区）。
- 协议级 E2E（真实 MCP stdio 客户端）：握手 `shining-world 1.0.0`、列出 **39** 个工具、九宫格 9 格绑定正确、
  `trigger_stream_step` 落盘、`step_all_due_streams` 8 成功 0 失败、OOC 校验拦截生效、
  蒸馏提案 → 审批 → 归档、快照生成 → 审批、`test_provider_connection` 全绿，输出 `E2E OK`。
- SSE 起服务：`GET http://127.0.0.1:8791/sse` 返回 **200**，日志显示 `Application startup complete`。

## 六、与文档的差异说明（已刻意取舍）

1. 文档写 `orchestrator.py` 单文件入口 → 实现为包内 `entry/cli.py`（等价入口，`python -m shining_world {sse,stdio,selfcheck}`），目录其余部分逐项对齐。
2. 向量库文档未指定后端 → 采用特征哈希 + 余弦的纯标准库实现，避免引入嵌入模型依赖与网络成本；仅承担兜底定位。
3. 一致性校验文档要求「防吃书、防 OOC」但未指定方式 → 实现为确定性规则（禁用词 / hard_rule 关键词 / 时序天数 / 地点规则），不额外消耗模型额度；`hard_rule` 同时写入 Prompt 做到双保险。
4. 文档「阶段一～六」是排期，本轮按用户要求一次性交付可用实现，排期表可作为验收清单逐项核对。
