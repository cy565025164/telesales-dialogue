"""
telesales-dialogue: 对话引擎主循环
电话销售多Agent协作对话系统
"""
import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from openai import AsyncOpenAI

client = AsyncOpenAI()
MODEL = "gpt-5"


@dataclass
class DialogueState:
    session_id: str
    customer_profile: dict = field(default_factory=lambda: {"name": "", "tags": []})
    current_node: str = "opening"
    turn_count: int = 0
    intent_history: list = field(default_factory=list)
    objection_count: int = 0
    buying_signals: int = 0
    conversation: list = field(default_factory=list)

    def to_dict(self):
        return self.__dict__


# ─── Intent Agent ───────────────────────────────────────────

INTENT_SYSTEM = """你是电话销售场景的用户意图识别专家。
根据用户最新发言和对话历史，输出严格JSON:
{"intent":"标签","confidence":0.0-1.0,"slots":{},"sentiment":"positive|neutral|negative|hostile"}
意图标签: buy_interest, price_inquiry, compare, objection_price, objection_need, objection_timing, hard_reject, feature_ask, policy_ask, delivery_ask, callback_request, transfer_human, hang_up, chitchat, unclear
confidence<0.6时intent设为unclear。"""


async def intent_agent(utterance: str, history: list[dict]) -> dict:
    messages = [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": f"对话历史:\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n用户最新发言: {utterance}"}
    ]
    resp = await client.chat.completions.create(
        model=MODEL, messages=messages,
        temperature=0.1, max_tokens=200,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)


# ─── Router Agent ───────────────────────────────────────────

ROUTER_SYSTEM = """你是电话销售流程控制专家。根据意图和状态决定下一节点。
输出严格JSON: {"next_node":"节点","strategy":"策略","priority_actions":["动作"]}
节点: opening, needs_discovery, product_pitch, objection_handling, trial_close, closing, graceful_exit, follow_up
策略: value_reframe, dig_deeper, fast_track, soft_close, momentum_close, respect_exit, re_engage, polite_end, de_escalate, schedule, transfer, time_wrap"""


async def router_agent(intent: dict, current_node: str, state: dict) -> dict:
    # 硬规则优先
    if intent["intent"] == "hard_reject" or intent.get("sentiment") == "hostile":
        return {"next_node": "graceful_exit", "strategy": "de_escalate", "priority_actions": ["respect_decision"]}
    if state["objection_count"] >= 3 and state["buying_signals"] == 0:
        return {"next_node": "graceful_exit", "strategy": "respect_exit", "priority_actions": ["leave_contact"]}

    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user", "content": json.dumps({
            "intent": intent, "current_node": current_node,
            "turn_count": state["turn_count"],
            "objection_count": state["objection_count"],
            "buying_signals": state["buying_signals"]
        }, ensure_ascii=False)}
    ]
    resp = await client.chat.completions.create(
        model=MODEL, messages=messages,
        temperature=0.1, max_tokens=150,
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)


# ─── Knowledge Agent ────────────────────────────────────────

async def knowledge_agent(intent: str, node: str, query: str) -> dict:
    """
    知识检索Agent - 实际项目中接入向量数据库
    此处为接口骨架，替换为真实RAG实现
    """
    # TODO: 替换为实际RAG检索
    # search_query = f"{intent} {node} {query}"
    # vec_results = await vector_store.search(search_query, top_k=20)
    # bm25_results = await bm25_index.search(search_query, top_k=20)
    # merged = rrf_merge(vec_results, bm25_results)
    # reranked = rerank_by_node(merged, node, intent)
    # return {"snippets": reranked[:5], "source_refs": [...]}

    return {"snippets": [], "source_refs": []}


# ─── Speech Agent ───────────────────────────────────────────

SPEECH_SYSTEM = """你是专业电话销售话术专家。根据上下文生成自然、专业的回复。
硬性约束:
1. ≤80字
2. 必须包含一个推进动作(提问/邀约/确认)
3. 禁止承诺知识库外的内容
4. 语气匹配客户情绪
5. 自然口语化，不要机械感
直接输出话术文本，无需格式包装。"""


async def speech_agent(intent: dict, node: str, strategy: str,
                       knowledge: list, history: list, customer: dict) -> str:
    context = {
        "intent": intent, "node": node, "strategy": strategy,
        "knowledge": knowledge, "customer": customer
    }
    messages = [
        {"role": "system", "content": SPEECH_SYSTEM},
        {"role": "user", "content": f"上下文:\n{json.dumps(context, ensure_ascii=False)}\n\n最近对话:\n{json.dumps(history[-6:], ensure_ascii=False)}\n\n请生成回复话术:"}
    ]
    resp = await client.chat.completions.create(
        model=MODEL, messages=messages,
        temperature=0.7, max_tokens=150, top_p=0.9
    )
    return resp.choices[0].message.content.strip()


# ─── 主循环 ─────────────────────────────────────────────────

def update_state(state: DialogueState, intent: dict, route: dict):
    state.turn_count += 1
    state.intent_history.append(intent["intent"])
    state.current_node = route["next_node"]
    if intent["intent"] in ("buy_interest", "price_inquiry"):
        state.buying_signals += 1
    if intent["intent"].startswith("objection_"):
        state.objection_count += 1


async def handle_turn(state: DialogueState, user_input: str) -> str:
    """处理单轮对话，返回话术回复"""
    # 记录用户输入
    state.conversation.append({"role": "customer", "content": user_input})

    # Step 1: 意图识别
    intent_result = await intent_agent(user_input, state.conversation)

    # Step 2: 流程路由
    route_result = await router_agent(intent_result, state.current_node, state.to_dict())

    # Step 3: 知识检索
    knowledge = await knowledge_agent(
        intent_result["intent"], route_result["next_node"], user_input
    )

    # Step 4: 话术生成
    response = await speech_agent(
        intent_result, route_result["next_node"], route_result["strategy"],
        knowledge["snippets"], state.conversation, state.customer_profile
    )

    # 更新状态
    update_state(state, intent_result, route_result)
    state.conversation.append({"role": "agent", "content": response})

    return response


# ─── 入口 ───────────────────────────────────────────────────

async def main():
    state = DialogueState(session_id="demo-001")
    print("=== 电话销售对话系统 (输入 quit 退出) ===\n")

    while True:
        user_input = input("客户: ")
        if user_input.strip().lower() == "quit":
            break

        response = await handle_turn(state, user_input)
        print(f"销售: {response}\n")
        print(f"  [状态] 节点={state.current_node} 轮次={state.turn_count} "
              f"异议={state.objection_count} 购买信号={state.buying_signals}")
        print()

        if state.current_node == "graceful_exit":
            print("--- 对话结束 ---")
            break


if __name__ == "__main__":
    asyncio.run(main())
