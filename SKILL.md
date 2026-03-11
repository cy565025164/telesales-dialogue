---
name: telesales-dialogue
description: |
  电话销售AI对话管理系统。基于单Agent多Skills架构，管理销售外呼全流程对话。
  单个GPT-5 Agent通过function calling调度4个Skill：意图识别、流程路由、知识检索、话术模板。
  适用于：电话销售外呼场景的对话状态管理、话术生成、异议处理、流程推进。
  当需要构建或运行电话销售对话系统时使用此技能。
---

# 电话销售对话管理系统 (Telesales Dialogue System)

## 架构总览

**单Agent + 多Skills**：一个 GPT-5 Agent 作为大脑统一推理，通过 function calling 按需调用技能。

```
                     ┌──────────────────────────┐
                     │      GPT-5 Agent         │
                     │   (单一推理中心)           │
                     │                          │
                     │  1. 理解用户意图          │
                     │  2. 决策调用哪些Skills     │
                     │  3. 整合结果生成话术       │
                     └──────┬───────────────────┘
                            │ function calling
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌──────────────┐ ┌──────────┐ ┌──────────────┐
     │ Skill:       │ │ Skill:   │ │ Skill:       │
     │ 知识检索      │ │ 流程查询  │ │ 客户画像查询  │
     │ search_kb()  │ │ get_flow()│ │ get_profile()│
     └──────────────┘ └──────────┘ └──────────────┘
```

### 与多Agent架构的区别

| 维度 | 多Agent（旧） | 单Agent多Skills（新） |
|------|-------------|---------------------|
| LLM调用次数 | 每轮4次 | 每轮1-2次（Agent自主决定） |
| 推理中心 | 分散，各Agent独立 | 统一，一个Agent全局推理 |
| 意图识别 | 独立Agent | Agent内置能力（System Prompt） |
| 流程路由 | 独立Agent | Agent内置能力 + get_flow() Skill辅助 |
| 知识获取 | 独立Agent | search_kb() Skill，按需调用 |
| 话术生成 | 独立Agent | Agent直接输出（核心能力） |
| 延迟 | 4次串行 ~4-8s | 1-2次 ~1-3s |
| 成本 | 4x token消耗 | ~1.5x token消耗 |

## Agent 定义

### System Prompt

Agent 的身份、能力、约束全部通过 System Prompt 注入。
完整 Prompt 见 `references/agent-system-prompt.md`

核心要点：
- 你是一位专业电话销售顾问
- 根据对话历史和客户画像，自然推进销售流程
- **不需要显式"识别意图"** — 你直接理解用户意思
- **不需要显式"选择节点"** — 你根据流程指南自然推进
- 需要产品/政策信息时，调用 `search_kb`
- 需要确认当前流程位置时，调用 `get_flow_guidance`
- 需要客户历史时，调用 `get_customer_profile`

### Skills（Tools）定义

Agent 通过 function calling 调用以下 Skills：

#### Skill 1: `search_kb` — 知识检索

```json
{
  "name": "search_kb",
  "description": "从知识库检索产品信息、价格、政策、异议应对策略等。当需要具体事实性信息来回答客户时调用。",
  "parameters": {
    "query": "检索关键词",
    "category": "product|objection|policy|script"
  }
}
```
- 实现：RAG混合检索（向量 + BM25）
- 详见 `references/skill-search-kb.md`

#### Skill 2: `get_flow_guidance` — 流程指引

```json
{
  "name": "get_flow_guidance",
  "description": "获取当前销售流程节点的指引和话术建议。当不确定下一步该怎么推进时调用。",
  "parameters": {
    "current_node": "opening|needs_discovery|product_pitch|objection_handling|trial_close|closing|graceful_exit",
    "situation": "简述当前情况"
  }
}
```
- 实现：查询流程配置 + 返回节点话术指南
- 流程定义见 `assets/flow_graph.json`

#### Skill 3: `get_customer_profile` — 客户画像

```json
{
  "name": "get_customer_profile",
  "description": "查询客户的历史信息、偏好、过往沟通记录。当需要个性化应对时调用。",
  "parameters": {
    "customer_id": "客户ID"
  }
}
```
- 实现：查询CRM系统
- 返回：客户标签、历史订单、上次沟通要点

#### Skill 4: `update_state` — 状态更新

```json
{
  "name": "update_state",
  "description": "更新对话状态。每轮结束后调用，记录流程推进情况。",
  "parameters": {
    "current_node": "当前流程节点",
    "buying_signal": "boolean, 是否检测到购买信号",
    "objection_type": "异议类型(可选)"
  }
}
```
- 实现：更新会话状态机
- 触发守护规则（异议次数超限 → 退出）

## 对话状态

```json
{
  "session_id": "uuid",
  "current_node": "opening",
  "turn_count": 0,
  "objection_count": 0,
  "buying_signals": 0,
  "conversation": []
}
```

守护规则（在状态更新时检查）：
- `objection_count >= 3` 且 `buying_signals == 0` → 强制 `graceful_exit`
- `turn_count > 15` → 触发收尾
- 客户明确拒绝 → `graceful_exit`

## 单轮调用流程

```python
async def handle_turn(state, user_input):
    # 1. 构建消息（System Prompt + 历史 + 当前状态 + 用户输入）
    messages = build_messages(state, user_input)

    # 2. 单次Agent调用（Agent自主决定是否调用Skills）
    response = await openai.chat.completions.create(
        model="gpt-5",
        messages=messages,
        tools=ALL_SKILLS,          # 4个Skills作为tools
        tool_choice="auto",        # Agent自主决定
        temperature=0.7,
    )

    # 3. 如果Agent调用了Skills，执行并返回结果
    while response has tool_calls:
        execute tool_calls → append results
        response = await openai.chat.completions.create(继续)

    # 4. Agent最终输出即为话术
    return response.content
```

**关键**：Agent 可能一次tool call都不调，直接回复（简单场景）；
也可能调1-2个Skills获取信息后再回复（需要查知识/确认流程时）。

## 配置

- **模型**: GPT-5, temperature=0.7
- **超时**: 全链路 ≤ 3s
- **降级**: Agent超时 → 用 `get_flow_guidance` 返回的静态模板兜底
- **话术约束**: 通过System Prompt控制（≤80字、必含推进动作）

## 参考文件

- `references/agent-system-prompt.md` — Agent完整System Prompt
- `references/skill-search-kb.md` — 知识检索Skill实现细节
- `references/flow-nodes.md` — 各流程节点的指引内容
- `scripts/dialogue_engine.py` — 对话引擎实现
- `scripts/api_server.py` — FastAPI服务
- `scripts/test_dialogue.py` — 测试用例
- `assets/flow_graph.json` — 流程图配置
