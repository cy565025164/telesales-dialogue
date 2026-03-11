"""
FastAPI 服务部署 - 电话销售多Agent对话系统
启动: uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000
"""
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from scripts.dialogue_engine import DialogueState, handle_turn


# ─── 会话存储 ───────────────────────────────────────────────

sessions: dict[str, DialogueState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Telesales Dialogue System started")
    yield
    sessions.clear()
    print("🛑 Telesales Dialogue System stopped")


app = FastAPI(
    title="电话销售AI对话系统",
    description="基于多Agent协作的电话销售话术生成服务",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── 请求/响应模型 ──────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    customer_name: Optional[str] = ""
    customer_tags: list[str] = Field(default_factory=list)


class CreateSessionResponse(BaseModel):
    session_id: str
    current_node: str


class ChatRequest(BaseModel):
    session_id: str
    user_input: str


class ChatResponse(BaseModel):
    session_id: str
    response: str
    current_node: str
    turn_count: int
    intent: str = ""
    sentiment: str = ""
    objection_count: int = 0
    buying_signals: int = 0
    is_terminal: bool = False


class SessionStatus(BaseModel):
    session_id: str
    current_node: str
    turn_count: int
    objection_count: int
    buying_signals: int
    intent_history: list[str]
    conversation_length: int


# ─── API 路由 ───────────────────────────────────────────────

@app.post("/sessions", response_model=CreateSessionResponse, tags=["会话管理"])
async def create_session(req: CreateSessionRequest):
    """创建新的对话会话"""
    sid = str(uuid.uuid4())[:8]
    state = DialogueState(
        session_id=sid,
        customer_profile={"name": req.customer_name, "tags": req.customer_tags},
    )
    sessions[sid] = state
    return CreateSessionResponse(session_id=sid, current_node=state.current_node)


@app.post("/chat", response_model=ChatResponse, tags=["对话"])
async def chat(req: ChatRequest):
    """发送用户消息，获取AI话术回复"""
    state = sessions.get(req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"会话 {req.session_id} 不存在")

    if state.current_node in ("graceful_exit", "follow_up") and state.turn_count > 0:
        return ChatResponse(
            session_id=req.session_id,
            response="对话已结束",
            current_node=state.current_node,
            turn_count=state.turn_count,
            is_terminal=True,
        )

    response = await handle_turn(state, req.user_input)

    # 从最新的intent_history获取本轮意图
    last_intent = state.intent_history[-1] if state.intent_history else ""
    # 从对话记录推断sentiment（简化）
    is_terminal = state.current_node in ("graceful_exit", "follow_up")

    return ChatResponse(
        session_id=req.session_id,
        response=response,
        current_node=state.current_node,
        turn_count=state.turn_count,
        intent=last_intent,
        objection_count=state.objection_count,
        buying_signals=state.buying_signals,
        is_terminal=is_terminal,
    )


@app.get("/sessions/{session_id}", response_model=SessionStatus, tags=["会话管理"])
async def get_session(session_id: str):
    """查询会话状态"""
    state = sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return SessionStatus(
        session_id=state.session_id,
        current_node=state.current_node,
        turn_count=state.turn_count,
        objection_count=state.objection_count,
        buying_signals=state.buying_signals,
        intent_history=state.intent_history,
        conversation_length=len(state.conversation),
    )


@app.delete("/sessions/{session_id}", tags=["会话管理"])
async def delete_session(session_id: str):
    """删除会话"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    del sessions[session_id]
    return {"message": f"会话 {session_id} 已删除"}


@app.get("/health", tags=["系统"])
async def health():
    return {"status": "ok", "active_sessions": len(sessions)}
