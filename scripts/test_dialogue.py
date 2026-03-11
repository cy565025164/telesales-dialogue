"""
对话测试用例 - 覆盖核心流程路径
运行: pytest scripts/test_dialogue.py -v
"""
import asyncio
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from scripts.dialogue_engine import (
    DialogueState, handle_turn, update_state,
    intent_agent, router_agent, speech_agent,
)


# ─── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def state():
    return DialogueState(session_id="test-001")


@pytest.fixture
def mock_openai():
    """Mock OpenAI API calls"""
    with patch("scripts.dialogue_engine.client") as mock_client:
        yield mock_client


def make_completion(content: str):
    """构造mock的OpenAI completion响应"""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


# ─── 状态管理测试 ───────────────────────────────────────────

class TestStateManagement:

    def test_initial_state(self, state):
        assert state.current_node == "opening"
        assert state.turn_count == 0
        assert state.objection_count == 0
        assert state.buying_signals == 0
        assert state.conversation == []

    def test_update_state_buying_signal(self, state):
        intent = {"intent": "buy_interest", "confidence": 0.9}
        route = {"next_node": "product_pitch", "strategy": "fast_track"}
        update_state(state, intent, route)
        assert state.buying_signals == 1
        assert state.turn_count == 1
        assert state.current_node == "product_pitch"

    def test_update_state_objection(self, state):
        intent = {"intent": "objection_price", "confidence": 0.85}
        route = {"next_node": "objection_handling", "strategy": "value_reframe"}
        update_state(state, intent, route)
        assert state.objection_count == 1

    def test_update_state_price_inquiry_is_buying_signal(self, state):
        intent = {"intent": "price_inquiry", "confidence": 0.9}
        route = {"next_node": "product_pitch", "strategy": "value_anchor"}
        update_state(state, intent, route)
        assert state.buying_signals == 1

    def test_intent_history_tracks(self, state):
        for intent_label in ["chitchat", "feature_ask", "buy_interest"]:
            intent = {"intent": intent_label, "confidence": 0.9}
            route = {"next_node": "product_pitch", "strategy": "test"}
            update_state(state, intent, route)
        assert state.intent_history == ["chitchat", "feature_ask", "buy_interest"]


# ─── Router 硬规则测试 ──────────────────────────────────────

class TestRouterHardRules:

    @pytest.mark.asyncio
    async def test_hard_reject_goes_to_exit(self):
        intent = {"intent": "hard_reject", "confidence": 0.95, "sentiment": "hostile"}
        state_dict = {"turn_count": 3, "objection_count": 0, "buying_signals": 0}
        result = await router_agent(intent, "product_pitch", state_dict)
        assert result["next_node"] == "graceful_exit"

    @pytest.mark.asyncio
    async def test_hostile_sentiment_goes_to_exit(self):
        intent = {"intent": "objection_price", "confidence": 0.8, "sentiment": "hostile"}
        state_dict = {"turn_count": 5, "objection_count": 1, "buying_signals": 0}
        result = await router_agent(intent, "product_pitch", state_dict)
        assert result["next_node"] == "graceful_exit"

    @pytest.mark.asyncio
    async def test_triple_objection_no_signal_exits(self):
        intent = {"intent": "objection_need", "confidence": 0.8, "sentiment": "negative"}
        state_dict = {"turn_count": 8, "objection_count": 3, "buying_signals": 0}
        result = await router_agent(intent, "objection_handling", state_dict)
        assert result["next_node"] == "graceful_exit"
        assert result["strategy"] == "respect_exit"


# ─── 全链路Mock测试 ─────────────────────────────────────────

class TestFullPipeline:

    @pytest.mark.asyncio
    async def test_happy_path_opening(self, state, mock_openai):
        """测试开场 → 意图识别 → 路由 → 话术生成"""
        intent_resp = json.dumps({
            "intent": "chitchat", "confidence": 0.8,
            "slots": {}, "sentiment": "neutral"
        })
        route_resp = json.dumps({
            "next_node": "needs_discovery",
            "strategy": "warm_transition",
            "priority_actions": ["ask_need"]
        })
        speech_resp = "您好，我是XX公司的小李。想了解一下您目前在用什么方案呢？"

        # 三次LLM调用的mock返回
        mock_openai.chat.completions.create = AsyncMock(side_effect=[
            make_completion(intent_resp),
            make_completion(route_resp),
            make_completion(speech_resp),
        ])

        result = await handle_turn(state, "喂，你好")
        assert result == speech_resp
        assert state.current_node == "needs_discovery"
        assert state.turn_count == 1

    @pytest.mark.asyncio
    async def test_buy_interest_path(self, state, mock_openai):
        """测试购买兴趣 → 直接推进到trial_close"""
        state.current_node = "product_pitch"
        state.turn_count = 5

        intent_resp = json.dumps({
            "intent": "buy_interest", "confidence": 0.88,
            "slots": {}, "sentiment": "positive"
        })
        route_resp = json.dumps({
            "next_node": "trial_close",
            "strategy": "soft_close",
            "priority_actions": ["confirm_order"]
        })
        speech_resp = "太好了！那我帮您预留一个名额，您看用哪个手机号注册呢？"

        mock_openai.chat.completions.create = AsyncMock(side_effect=[
            make_completion(intent_resp),
            make_completion(route_resp),
            make_completion(speech_resp),
        ])

        result = await handle_turn(state, "嗯，挺感兴趣的，怎么买")
        assert state.current_node == "trial_close"
        assert state.buying_signals == 1

    @pytest.mark.asyncio
    async def test_objection_handling_path(self, state, mock_openai):
        """测试价格异议处理"""
        state.current_node = "product_pitch"

        intent_resp = json.dumps({
            "intent": "objection_price", "confidence": 0.92,
            "slots": {"competitor_price": "500"}, "sentiment": "negative"
        })
        route_resp = json.dumps({
            "next_node": "objection_handling",
            "strategy": "value_reframe",
            "priority_actions": ["reframe_value"]
        })
        speech_resp = "理解您的顾虑，算下来每天不到3块钱，比一杯咖啡还便宜。关键是能帮您省下XX时间，您觉得呢？"

        mock_openai.chat.completions.create = AsyncMock(side_effect=[
            make_completion(intent_resp),
            make_completion(route_resp),
            make_completion(speech_resp),
        ])

        result = await handle_turn(state, "太贵了，别家才500")
        assert state.current_node == "objection_handling"
        assert state.objection_count == 1

    @pytest.mark.asyncio
    async def test_hard_reject_terminates(self, state, mock_openai):
        """测试强拒绝直接结束（Router硬规则，不调用LLM Router）"""
        state.current_node = "product_pitch"

        intent_resp = json.dumps({
            "intent": "hard_reject", "confidence": 0.95,
            "slots": {}, "sentiment": "hostile"
        })
        # Router硬规则触发，不会调用LLM，只需intent + speech两次调用
        speech_resp = "好的，非常抱歉打扰您了。如果以后有需要，随时联系我们。祝您生活愉快！"

        mock_openai.chat.completions.create = AsyncMock(side_effect=[
            make_completion(intent_resp),
            make_completion(speech_resp),
        ])

        result = await handle_turn(state, "别打了，不需要")
        assert state.current_node == "graceful_exit"


# ─── API 服务测试 ───────────────────────────────────────────

class TestAPIServer:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from scripts.api_server import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_create_session(self, client):
        resp = client.post("/sessions", json={"customer_name": "张三"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["current_node"] == "opening"

    def test_get_nonexistent_session(self, client):
        resp = client.get("/sessions/nonexistent")
        assert resp.status_code == 404

    def test_delete_session(self, client):
        # 先创建
        resp = client.post("/sessions", json={})
        sid = resp.json()["session_id"]
        # 再删除
        resp = client.delete(f"/sessions/{sid}")
        assert resp.status_code == 200
        # 确认已删
        resp = client.get(f"/sessions/{sid}")
        assert resp.status_code == 404
