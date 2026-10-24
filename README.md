# 闪亮大世界 ShiningWorld

多支线群像剧情推演系统 · 自研 MCP 调度服务（唯一核心服务）。

顶层链路固定不变：

```
DSH 九宫格主控台（MCP 客户端）
        ↓  MCP（stdio / SSE 双协议）
闪亮大世界自研 MCP 调度服务（本仓库）
        ↓  模型适配器层
多家 OpenAI 兼容 API（付费 API + 免费 API 池，自动负载、重试、故障切换）
```

## 解决什么问题

| 痛点 | 本方案的做法 |
| --- | --- |
| 长篇对话角色失忆 | 分段快照归档 + 人工审批 + 只保留最新快照与近期对话 |
| 人设 OOC | 角色卡固化 `stable` 与 `hard_rule`，生成后自动校验，越线只冻结该支线 |
| 多阵营信息穿帮 | 标签检索按阵营权限过滤，`secret` 字段受控显示 |
| 设定吃书 | 世界观变更一律走「提案 → 人工审批」才落库，保留版本与回滚 |
| 单支线失控拖垮全局 | 每条支线独立状态机（运行/暂停/冷却/告警），独立冷却计时 |

## 快速开始

```bash
# 1. 建虚拟环境（Python ≥ 3.12）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. 初始化世界观种子 + 9 条九宫格支线
.venv\Scripts\python.exe scripts\init_world.py --config config.yaml

# 3. 自检（不联网，走本地 mock 服务商）
.venv\Scripts\python.exe -m shining_world selfcheck --config config.yaml

# 4. 起服务（二选一）
.venv\Scripts\python.exe -m shining_world sse     --config config.yaml   # 主推：HTTP/SSE
.venv\Scripts\python.exe -m shining_world stdio   --config config.yaml   # DSH 本地子进程
```

SSE 默认地址：`http://127.0.0.1:8791/sse`，消息端点 `/messages/`。

## 接入 DSH

`mcp.json`（stdio 方式）：

```json
{
  "mcpServers": {
    "shining-world": {
      "command": "E:\\dd\\ShiningWorld\\.venv\\Scripts\\python.exe",
      "args": ["-m", "shining_world", "stdio", "--config", "E:\\dd\\ShiningWorld\\config.yaml"],
      "env": { "PYTHONPATH": "E:\\dd\\ShiningWorld\\src" }
    }
  }
}
```

SSE 方式只需在 DSH 里新增一条 SSE 连接：`http://127.0.0.1:8791/sse`。

## 目录结构

```
ShiningWorld/
├── config.yaml                 # 服务商、限流、检索、快照、九宫格预设
├── pyproject.toml
├── scripts/init_world.py       # 一键录入种子数据 + 建 9 条支线
├── src/shining_world/
│   ├── orchestrator 等价入口   # entry/cli.py（stdio / SSE / selfcheck）
│   ├── config/                 # 配置模型与加载（含 ${ENV} 展开）
│   ├── providers/              # 统一适配器 + OpenAI 兼容 + mock + 调度池
│   ├── retrieval/              # 标签倒排索引 + 轻量向量库 + 融合检索
│   ├── world/                  # 剧情池/地图池/人文池/人物池 + 提案审批
│   ├── streams/                # 支线状态机 + 快照归档
│   ├── consistency/            # OOC / 时序 / 世界观规则校验
│   ├── narrative/              # 上下文拼装 + 三套 Prompt + 蒸馏 + 推演引擎
│   ├── tools/                  # 工具门面（信封化）
│   └── server/                 # MCP Server 装配
├── tests/                      # 80 个用例，全离线
├── prompts/                    # 可编辑的 Prompt 副本
├── docs/                       # 使用手册、标签规范、架构分层、MCP 清单
├── world-bible/                # 运行时生成：四大子库 + index.json
├── vector_db/                  # 运行时生成：向量持久化
├── streams/                    # 运行时生成：支线数据
└── logs/                       # 运行时生成：shining-world.log（按天轮转，保留 14 天）
```

## 工具全集（45 个）

按文档 5.x 分六组：系统（1）、模型服务商管理（4）、叙事流管理（9）、检索（5）、世界观池子与审批（18）、快照记忆（4）、一致性校验（4）—— 合计 45 个。完整签名见 `docs/mcp-tools.md`。

## 设计取舍

- **只依赖 `mcp` + `PyYAML`**：HTTP 用标准库 `urllib`，向量用特征哈希 + 余弦，不引入重依赖，部署即跑。
- **向量仅兜底**：标签命中 ≥ 阈值时不启动向量，保证设定稳定可控、结果可复现。
- **校验不耗额度**：一致性校验是确定性规则（禁用词、硬性规则、时序、地点规则），不额外调用模型。
- **所有写操作可审计**：世界观变更走提案队列，角色卡带版本历史，支线历史落 JSONL。

## 测试

```bash
.venv\Scripts\python.exe -m pytest -q
# 80 passed
```

## 文档

- `docs/usage.md` — 完整业务流程与操作手册（对应文档第 6 节）
- `docs/mcp-tools.md` — 38 个 MCP 工具签名与返回示例
- `docs/tag-spec.md` — 标签使用规范
- `docs/architecture.md` — 架构分层图（逐层展开）
- `docs/dsh-panel.md` — DSH 九宫格面板配置描述
- `docs/templates/` — 角色卡 / 事件 / 支线模板 JSON
