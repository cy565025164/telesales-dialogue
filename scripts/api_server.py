"""
FastAPI 服务 — 单Agent多Skills电话销售对话系统
启动: uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000
"""
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from scripts.dialogue_engine import DialogueState, handle_turn


sessions: dict[str, DialogueState] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Telesales Dialogue System [Single Agent + Multi Skills] started")
    yield
    sessions.clear()


app = FastAPI(
    title="电话销售AI对话系统",
    description="单Agent多Skills架构 — GPT-5通过function calling调度技能",
    version="2.0.0",
    lifespan=lifespan,
)


# ─── 模型 ───────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    customer_id: Optional[str] = ""
    customer_name: Optional[str] = ""


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
    objection_count: int = 0
    buying_signals: int = 0
    is_terminal: bool = False


class SessionStatus(BaseModel):
    session_id: str
    current_node: str
    turn_count: int
    objection_count: int
    buying_signals: int
    conversation_length: int


# ─── API ────────────────────────────────────────────────────

@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    sid = str(uuid.uuid4())[:8]
    state = DialogueState(session_id=sid, customer_id=req.customer_id or "")
    sessions[sid] = state
    return CreateSessionResponse(session_id=sid, current_node=state.current_node)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    state = sessions.get(req.session_id)
    if not state:
        raise HTTPException(404, f"会话 {req.session_id} 不存在")

    if state.current_node == "graceful_exit" and state.turn_count > 0:
        return ChatResponse(
            session_id=req.session_id, response="对话已结束",
            current_node=state.current_node, turn_count=state.turn_count,
            is_terminal=True,
        )

    response = await handle_turn(state, req.user_input)
    return ChatResponse(
        session_id=req.session_id, response=response,
        current_node=state.current_node, turn_count=state.turn_count,
        objection_count=state.objection_count,
        buying_signals=state.buying_signals,
        is_terminal=state.current_node == "graceful_exit",
    )


@app.get("/sessions/{session_id}", response_model=SessionStatus)
async def get_session(session_id: str):
    state = sessions.get(session_id)
    if not state:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return SessionStatus(
        session_id=state.session_id, current_node=state.current_node,
        turn_count=state.turn_count, objection_count=state.objection_count,
        buying_signals=state.buying_signals,
        conversation_length=len(state.conversation),
    )


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    del sessions[session_id]
    return {"message": f"会话 {session_id} 已删除"}


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "arch": "single-agent-multi-skills", "active_sessions": len(sessions)}
