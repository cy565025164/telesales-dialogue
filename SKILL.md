---
name: telesales-dialogue
description: |
  电话销售AI对话管理系统。基于多Agent协作架构，管理销售外呼全流程对话。
  包含：意图识别、流程路由、知识检索、话术生成四个核心Agent。
  适用于：电话销售外呼场景的对话状态管理、话术生成、异议处理、流程推进。
  当需要构建或运行电话销售对话系统时使用此技能。
---

# 电话销售对话管理系统 (Telesales Dialogue System)

## 架构总览

```
用户语音/文本输入
       │
       ▼
┌─────────────────┐
│  Intent Agent    │ ← 意图识别 (GPT-5)
│  识别用户意图     │
└───────┬─────────┘
        │ intent + slots
        ▼
┌─────────────────┐
│  Router Agent    │ ← 流程路由 (GPT-5)
│  决策下一节点     │
└───────┬─────────┘
        │ next_node + context
        ▼
┌─────────────────┐
│  Knowledge Agent │ ← 知识检索 (RAG + Embedding)
│  检索回答素材     │
└───────┬─────────┘
        │ knowledge_snippets
        ▼
┌─────────────────┐
│  Speech Agent    │ ← 话术生成 (GPT-5)
│  生成最终回复     │
└───────┴─────────┘
        │
        ▼
    话术输出
```

## 核心Agent定义

### 1. Intent Agent（意图识别）

- **模型**: GPT-5
- **输入**: 当前用户utterance + 最近N轮对话历史
- **输出**: `{ intent, confidence, slots, sentiment }`
- **Prompt模板**: 见 `references/intent-agent.md`

意图分类体系：
| 类别 | 示例意图 |
|------|---------|
| 购买意向 | `buy_interest`, `price_inquiry`, `compare` |
| 异议拒绝 | `objection_price`, `objection_need`, `objection_timing`, `hard_reject` |
| 信息咨询 | `feature_ask`, `policy_ask`, `delivery_ask` |
| 流程控制 | `callback_request`, `transfer_human`, `hang_up` |
| 闲聊/其他 | `chitchat`, `unclear`, `silence` |

### 2. Router Agent（流程路由）

- **模型**: GPT-5
- **输入**: intent结果 + 当前流程节点 + 对话状态
- **输出**: `{ next_node, strategy, priority_actions }`
- **流程图定义**: 见 `references/flow-graph.md`

核心流程节点：
```
opening → needs_discovery → product_pitch → objection_handling → trial_close → closing
                                  ↑               │
                                  └───────────────┘ (循环处理异议)
```

路由规则：
- 强拒绝(hard_reject) → 直接进入 `graceful_exit`
- 价格异议 → `objection_handling` + strategy=`value_reframe`
- 购买信号 → 跳转 `trial_close`
- 沉默/不清晰 → 保持当前节点 + strategy=`re_engage`

### 3. Knowledge Agent（知识检索）

- **检索引擎**: RAG (向量检索 + BM25混合)
- **输入**: intent + next_node + user_query
- **输出**: `{ snippets[], source_refs[] }`
- **知识库结构**: 见 `references/knowledge-base.md`

知识库分层：
1. **产品库** — 功能、规格、价格、对比
2. **话术库** — 按流程节点 × 意图类型索引的话术模板
3. **异议库** — 常见异议及应对策略
4. **政策库** — 退换货、售后、合规话术

检索策略：
- query = `f"{intent_label} {next_node} {user_utterance}"`
- top_k = 5, rerank by node relevance
- 必须包含合规免责片段（如涉及价格承诺）

### 4. Speech Agent（话术生成）

- **模型**: GPT-5
- **输入**: intent结果 + next_node + knowledge_snippets + 对话历史 + 客户画像
- **输出**: 最终话术文本
- **Prompt模板**: 见 `references/speech-agent.md`

生成约束：
- 单次回复 ≤ 80字（电话场景简洁为王）
- 必须包含一个推进动作（提问/邀约/确认）
- 禁止承诺合同外内容
- 语气匹配客户情绪（sentiment-aware）

## 对话状态管理

```json
{
  "session_id": "uuid",
  "customer_profile": { "name": "", "history": [], "tags": [] },
  "current_node": "opening",
  "turn_count": 0,
  "intent_history": [],
  "objection_count": 0,
  "buying_signals": 0,
  "conversation": []
}
```

状态更新规则：
- 每轮更新 `intent_history`, `turn_count`
- `buying_signals` 累加（`buy_interest`/`price_inquiry` 各+1）
- `objection_count >= 3` 且无buying_signal → 触发 `graceful_exit`
- `turn_count > 15` → 触发总结收尾

## 调用流程（伪代码）

```python
async def handle_turn(state, user_input):
    # Step 1: 意图识别
    intent_result = await intent_agent.run(
        utterance=user_input,
        history=state["conversation"][-6:]  # 最近3轮
    )

    # Step 2: 流程路由
    route_result = await router_agent.run(
        intent=intent_result,
        current_node=state["current_node"],
        state=state
    )

    # Step 3: 知识检索
    knowledge = await knowledge_agent.search(
        intent=intent_result["intent"],
        node=route_result["next_node"],
        query=user_input
    )

    # Step 4: 话术生成
    response = await speech_agent.run(
        intent=intent_result,
        node=route_result["next_node"],
        strategy=route_result["strategy"],
        knowledge=knowledge["snippets"],
        history=state["conversation"][-6:],
        customer=state["customer_profile"]
    )

    # 更新状态
    update_state(state, intent_result, route_result)

    return response
```

## 配置与调优

- **模型温度**: Intent/Router Agent → 0.1 (确定性), Speech Agent → 0.7 (自然度)
- **超时**: 单Agent ≤ 2s, 全链路 ≤ 5s（电话场景延迟敏感）
- **降级**: 若任一Agent超时，使用话术库静态模板兜底
- **A/B测试**: Speech Agent支持多Prompt版本并行，按转化率择优

## 参考文件

- `references/intent-agent.md` — Intent Agent详细Prompt及Few-shot示例
- `references/router-agent.md` — Router Agent路由规则及流程图详述
- `references/knowledge-base.md` — 知识库schema及索引策略
- `references/speech-agent.md` — Speech Agent Prompt模板及生成约束
- `scripts/dialogue_engine.py` — 对话引擎主循环实现
- `scripts/state_manager.py` — 状态管理器
- `assets/flow_graph.json` — 流程图节点定义（可配置）
