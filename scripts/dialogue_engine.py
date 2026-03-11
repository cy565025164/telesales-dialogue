"""
telesales-dialogue: 单Agent多Skills对话引擎
一个GPT-5 Agent通过function calling按需调用Skills
"""
import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from openai import AsyncOpenAI

client = AsyncOpenAI()
MODEL = "gpt-5"

# ─── System Prompt ──────────────────────────────────────────

SYSTEM_PROMPT = """你是一位专业的电话销售顾问，正在与客户进行电话沟通。

## 你的身份
- 专业、友好、不卑不亢
- 语气自然口语化，像真人通话
- 不使用"亲"、"宝"等过度亲昵称呼

## 销售流程指南
按以下节点推进，根据客户反应灵活调整：
1. opening — 简短自我介绍，建立话题
2. needs_discovery — 开放式问题了解痛点
3. product_pitch — 结合需求讲利益点
4. objection_handling — 先认同再转化
5. trial_close — 假设成交法/二选一法
6. closing — 确认细节，表达感谢
7. graceful_exit — 不纠缠，真诚告别

## 何时使用Skills
- search_kb: 客户问具体产品/价格/政策/竞品时
- get_flow_guidance: 不确定该怎么推进时
- get_customer_profile: 需要个性化沟通时
- update_state: 每轮回复后记录当前节点

简单寒暄/过渡不需要调用任何Skill，直接回复。

## 硬性约束
1. 每次回复 ≤ 80字
2. 必须包含一个推进动作（提问/邀约/确认）
3. 不承诺知识库以外的信息
4. 感知客户情绪调整语气
5. 客户连续3次拒绝且无购买信号 → 礼貌结束
6. 客户说"不要打了"/"挂了" → 立即礼貌告别

## 输出
直接输出话术。不要思考过程、不要标注节点、不要格式包装。"""


# ─── 对话状态 ───────────────────────────────────────────────

@dataclass
class DialogueState:
    session_id: str
    customer_id: str = ""
    current_node: str = "opening"
    turn_count: int = 0
    objection_count: int = 0
    buying_signals: int = 0
    conversation: list = field(default_factory=list)

    def to_dict(self):
        return {
            "current_node": self.current_node,
            "turn_count": self.turn_count,
            "objection_count": self.objection_count,
            "buying_signals": self.buying_signals,
        }


# ─── Skills 定义 (Tools) ───────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "从知识库检索产品信息、价格、政策、异议应对策略等。当需要具体事实性信息来回答客户时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词"},
                    "category": {
                        "type": "string",
                        "enum": ["product", "objection", "policy", "script"],
                        "description": "知识库分类",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_flow_guidance",
            "description": "获取当前销售流程节点的指引和话术建议。当不确定下一步该怎么推进时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_node": {
                        "type": "string",
                        "enum": [
                            "opening", "needs_discovery", "product_pitch",
                            "objection_handling", "trial_close", "closing",
                            "graceful_exit",
                        ],
                        "description": "当前流程节点",
                    },
                    "situation": {"type": "string", "description": "简述当前情况"},
                },
                "required": ["current_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": "查询客户历史信息、偏好、过往沟通记录。当需要个性化应对时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "客户ID"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_state",
            "description": "更新对话状态。每轮回复后调用，记录流程推进。",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_node": {"type": "string", "description": "当前流程节点"},
                    "buying_signal": {"type": "boolean", "description": "是否检测到购买信号"},
                    "objection_type": {"type": "string", "description": "异议类型(可选)"},
                },
                "required": ["current_node"],
            },
        },
    },
]


# ─── Skills 实现 ────────────────────────────────────────────

# 流程指引内容
FLOW_GUIDANCE = {
    "opening": "目标：30秒建立对话意愿。自报家门+一句话说来意，用客户能关联的信息破冰。→ 自然过渡到needs_discovery",
    "needs_discovery": "目标：找到真实痛点。用开放式问题，听到痛点后追问细节，不急于介绍产品。→ 痛点明确后进product_pitch",
    "product_pitch": "目标：价值与痛点对接。先回应痛点再说产品怎么解决，讲利益不讲参数，用案例佐证。→ 购买信号时进trial_close",
    "objection_handling": "目标：化解顾虑。价格→换算日均/ROI，需求→关联痛点，时间→限时优惠。先说理解再转化。→ 化解后进trial_close，3次无效进graceful_exit",
    "trial_close": "目标：推动决策。假设成交法或二选一法，总结价值后直接推进。→ 同意进closing，新异议回objection_handling",
    "closing": "目标：锁定订单。确认关键信息，说明下一步，表达感谢。",
    "graceful_exit": "目标：保持好印象。不纠缠，加微信留触点，真诚告别。",
}


async def execute_skill(name: str, args: dict, state: DialogueState) -> str:
    """执行Skill并返回结果"""

    if name == "search_kb":
        return await skill_search_kb(args.get("query", ""), args.get("category", "product"))

    elif name == "get_flow_guidance":
        node = args.get("current_node", state.current_node)
        situation = args.get("situation", "")
        guidance = FLOW_GUIDANCE.get(node, "按当前情况灵活应对。")
        return json.dumps({"node": node, "guidance": guidance, "situation": situation}, ensure_ascii=False)

    elif name == "get_customer_profile":
        return await skill_get_customer_profile(args.get("customer_id", state.customer_id))

    elif name == "update_state":
        node = args.get("current_node", state.current_node)
        buying = args.get("buying_signal", False)
        objection = args.get("objection_type")

        state.current_node = node
        if buying:
            state.buying_signals += 1
        if objection:
            state.objection_count += 1

        # 守护规则
        force_exit = False
        if state.objection_count >= 3 and state.buying_signals == 0:
            state.current_node = "graceful_exit"
            force_exit = True

        return json.dumps({
            "updated": True,
            "current_node": state.current_node,
            "force_exit": force_exit,
            "state": state.to_dict(),
        }, ensure_ascii=False)

    return json.dumps({"error": f"Unknown skill: {name}"})


async def skill_search_kb(query: str, category: str = "product") -> str:
    """知识检索Skill — 接入实际RAG系统"""
    # TODO: 替换为实际向量数据库检索
    # vec_results = await vector_store.search(query, top_k=20)
    # bm25_results = await bm25_index.search(query, top_k=20)
    # merged = rrf_merge(vec_results, bm25_results)
    # return json.dumps({"snippets": merged[:5]})
    return json.dumps({
        "snippets": [f"[知识库] 关于'{query}'的检索结果（接入RAG后替换）"],
        "category": category,
        "note": "请接入实际知识库",
    }, ensure_ascii=False)


async def skill_get_customer_profile(customer_id: str) -> str:
    """客户画像Skill — 接入实际CRM"""
    # TODO: 替换为实际CRM查询
    return json.dumps({
        "customer_id": customer_id,
        "name": "",
        "tags": [],
        "history": [],
        "note": "请接入实际CRM系统",
    }, ensure_ascii=False)


# ─── Agent 主循环 ───────────────────────────────────────────

def build_messages(state: DialogueState, user_input: str) -> list:
    """构建发送给Agent的消息列表"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 注入当前状态
    state_info = f"[当前状态] 节点={state.current_node} 轮次={state.turn_count} 异议={state.objection_count} 购买信号={state.buying_signals}"
    messages.append({"role": "system", "content": state_info})

    # 历史对话（最近6条）
    for msg in state.conversation[-6:]:
        role = "assistant" if msg["role"] == "agent" else "user"
        messages.append({"role": role, "content": msg["content"]})

    # 当前用户输入
    messages.append({"role": "user", "content": user_input})
    return messages


async def handle_turn(state: DialogueState, user_input: str) -> str:
    """处理单轮对话 — 单Agent + function calling"""
    state.conversation.append({"role": "customer", "content": user_input})
    state.turn_count += 1

    messages = build_messages(state, user_input)

    # Agent调用（可能触发0~N次tool calls）
    max_rounds = 5  # 防止无限循环
    for _ in range(max_rounds):
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=300,
        )

        msg = response.choices[0].message

        # 如果Agent直接回复（无tool call），结束
        if not msg.tool_calls:
            result = msg.content.strip()
            state.conversation.append({"role": "agent", "content": result})
            return result

        # 执行所有tool calls
        messages.append(msg)  # 添加assistant的tool_call消息
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            skill_result = await execute_skill(tc.function.name, args, state)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": skill_result,
            })

    # 降级：超过最大轮次，用流程指引兜底
    fallback = FLOW_GUIDANCE.get(state.current_node, "请问您还有什么想了解的？")
    state.conversation.append({"role": "agent", "content": fallback})
    return fallback


# ─── CLI 入口 ───────────────────────────────────────────────

async def main():
    state = DialogueState(session_id="demo-001", customer_id="C001")
    print("=== 电话销售对话系统 [单Agent多Skills] (输入 quit 退出) ===\n")

    while True:
        user_input = input("客户: ")
        if user_input.strip().lower() == "quit":
            break

        response = await handle_turn(state, user_input)
        print(f"销售: {response}")
        print(f"  [状态] 节点={state.current_node} 轮次={state.turn_count} "
              f"异议={state.objection_count} 购买信号={state.buying_signals}\n")

        if state.current_node == "graceful_exit":
            print("--- 对话结束 ---")
            break


if __name__ == "__main__":
    asyncio.run(main())
