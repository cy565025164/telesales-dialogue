"""
测试用例 — 单Agent多Skills架构
运行: pytest scripts/test_dialogue.py -v
"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from scripts.dialogue_engine import (
    DialogueState, handle_turn, execute_skill,
    build_messages, TOOLS, FLOW_GUIDANCE,
)


# ─── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def state():
    return DialogueState(session_id="test-001", customer_id="C001")


@pytest.fixture
def mock_openai():
    with patch("scripts.dialogue_engine.client") as mock_client:
        yield mock_client


def make_completion(content=None, tool_calls=None):
    """构造mock的OpenAI响应"""
    mock_resp = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls
    mock_resp.choices = [MagicMock(message=mock_msg)]
    return mock_resp


def make_tool_call(name, args, call_id="tc_001"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


# ─── 状态管理测试 ───────────────────────────────────────────

class TestDialogueState:

    def test_initial_state(self, state):
        assert state.current_node == "opening"
        assert state.turn_count == 0
        assert state.objection_count == 0
        assert state.buying_signals == 0

    def test_to_dict(self, state):
        d = state.to_dict()
        assert d["current_node"] == "opening"
        assert "turn_count" in d


# ─── Skills 执行测试 ───────────────────────────────────────

class TestSkillExecution:

    @pytest.mark.asyncio
    async def test_search_kb(self, state):
        result = await execute_skill("search_kb", {"query": "价格", "category": "product"}, state)
        data = json.loads(result)
        assert "snippets" in data

    @pytest.mark.asyncio
    async def test_get_flow_guidance(self, state):
        result = await execute_skill("get_flow_guidance", {"current_node": "opening"}, state)
        data = json.loads(result)
        assert data["node"] == "opening"
        assert "guidance" in data

    @pytest.mark.asyncio
    async def test_get_customer_profile(self, state):
        result = await execute_skill("get_customer_profile", {"customer_id": "C001"}, state)
        data = json.loads(result)
        assert data["customer_id"] == "C001"

    @pytest.mark.asyncio
    async def test_update_state_buying_signal(self, state):
        result = await execute_skill(
            "update_state",
            {"current_node": "product_pitch", "buying_signal": True},
            state,
        )
        assert state.buying_signals == 1
        assert state.current_node == "product_pitch"

    @pytest.mark.asyncio
    async def test_update_state_objection(self, state):
        result = await execute_skill(
            "update_state",
            {"current_node": "objection_handling", "objection_type": "price"},
            state,
        )
        assert state.objection_count == 1

    @pytest.mark.asyncio
    async def test_update_state_force_exit(self, state):
        """3次异议 + 0购买信号 → 强制graceful_exit"""
        state.objection_count = 2
        state.buying_signals = 0
        result = await execute_skill(
            "update_state",
            {"current_node": "objection_handling", "objection_type": "need"},
            state,
        )
        data = json.loads(result)
        assert data["force_exit"] is True
        assert state.current_node == "graceful_exit"

    @pytest.mark.asyncio
    async def test_unknown_skill(self, state):
        result = await execute_skill("nonexistent", {}, state)
        data = json.loads(result)
        assert "error" in data


# ─── 消息构建测试 ──────────────────────────────────────────

class TestBuildMessages:

    def test_basic_messages(self, state):
        msgs = build_messages(state, "你好")
        assert msgs[0]["role"] == "system"  # system prompt
        assert msgs[1]["role"] == "system"  # state info
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "你好"

    def test_includes_history(self, state):
        state.conversation = [
            {"role": "customer", "content": "你好"},
            {"role": "agent", "content": "您好！"},
        ]
        msgs = build_messages(state, "多少钱")
        # system + state + 2 history + user = 5
        assert len(msgs) == 5


# ─── Tools定义验证 ─────────────────────────────────────────

class TestToolsDefinition:

    def test_four_tools_defined(self):
        assert len(TOOLS) == 4

    def test_tool_names(self):
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {"search_kb", "get_flow_guidance", "get_customer_profile", "update_state"}

    def test_all_flow_nodes_covered(self):
        expected = {"opening", "needs_discovery", "product_pitch",
                    "objection_handling", "trial_close", "closing", "graceful_exit"}
        assert set(FLOW_GUIDANCE.keys()) == expected


# ─── Agent全链路Mock测试 ───────────────────────────────────

class TestAgentPipeline:

    @pytest.mark.asyncio
    async def test_direct_reply_no_tool_call(self, state, mock_openai):
        """简单场景：Agent直接回复，不调用任何Skill"""
        mock_openai.chat.completions.create = AsyncMock(
            return_value=make_completion(content="您好，我是XX公司的小李，耽误您一分钟了解下我们的新产品？")
        )
        result = await handle_turn(state, "喂")
        assert "您好" in result
        assert state.turn_count == 1

    @pytest.mark.asyncio
    async def test_with_search_kb_call(self, state, mock_openai):
        """Agent先调search_kb获取信息，再生成回复"""
        state.current_node = "product_pitch"

        # 第一次返回tool_call
        tool_call = make_tool_call("search_kb", {"query": "价格", "category": "product"})
        resp1 = make_completion(tool_calls=[tool_call])
        # 第二次返回最终回复
        resp2 = make_completion(content="我们套餐月费99元，算下来每天不到3块钱，您觉得怎么样？")

        mock_openai.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])
        result = await handle_turn(state, "你们这个多少钱")
        assert "99" in result or "怎么样" in result

    @pytest.mark.asyncio
    async def test_with_update_state_call(self, state, mock_openai):
        """Agent回复后调用update_state更新节点"""
        # 第一次：tool_call update_state
        tool_call = make_tool_call("update_state", {
            "current_node": "needs_discovery", "buying_signal": False
        })
        resp1 = make_completion(tool_calls=[tool_call])
        # 第二次：最终回复
        resp2 = make_completion(content="方便问一下，您目前最头疼的问题是什么呢？")

        mock_openai.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])
        result = await handle_turn(state, "嗯你说")
        assert state.current_node == "needs_discovery"

    @pytest.mark.asyncio
    async def test_multi_tool_calls(self, state, mock_openai):
        """Agent一次调用多个Skills"""
        state.current_node = "product_pitch"

        tc1 = make_tool_call("search_kb", {"query": "竞品对比"}, "tc_001")
        tc2 = make_tool_call("update_state", {"current_node": "objection_handling", "objection_type": "compare"}, "tc_002")
        resp1 = make_completion(tool_calls=[tc1, tc2])
        resp2 = make_completion(content="和他们比，我们最大的优势是售后响应速度，24小时内解决问题。您看重售后吗？")

        mock_openai.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])
        result = await handle_turn(state, "你们比XX好在哪")
        assert state.objection_count == 1

    @pytest.mark.asyncio
    async def test_fallback_on_max_rounds(self, state, mock_openai):
        """超过最大轮次，降级使用静态指引"""
        # 每次都返回tool_call，模拟死循环
        tool_call = make_tool_call("search_kb", {"query": "test"})
        mock_resp = make_completion(tool_calls=[tool_call])
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await handle_turn(state, "你好")
        # 应该降级到FLOW_GUIDANCE
        assert result == FLOW_GUIDANCE.get(state.current_node)


# ─── API 测试 ──────────────────────────────────────────────

class TestAPI:

    @pytest.fixture
    def api_client(self):
        from fastapi.testclient import TestClient
        from scripts.api_server import app
        return TestClient(app)

    def test_health(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["arch"] == "single-agent-multi-skills"

    def test_create_and_get_session(self, api_client):
        resp = api_client.post("/sessions", json={"customer_id": "C001"})
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert resp.json()["current_node"] == "opening"

        resp = api_client.get(f"/sessions/{sid}")
        assert resp.status_code == 200

    def test_delete_session(self, api_client):
        resp = api_client.post("/sessions", json={})
        sid = resp.json()["session_id"]
        assert api_client.delete(f"/sessions/{sid}").status_code == 200
        assert api_client.get(f"/sessions/{sid}").status_code == 404

    def test_404_on_missing_session(self, api_client):
        assert api_client.get("/sessions/nope").status_code == 404
