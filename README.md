# 电话销售AI对话系统

**单Agent + 多Skills 架构** — 一个 GPT-5 Agent 通过 function calling 按需调度技能。

## 架构

```
                  ┌────────────────────┐
                  │    GPT-5 Agent     │  ← 统一推理中心
                  │  (System Prompt)   │
                  └──────┬─────────────┘
                         │ function calling (按需)
           ┌─────────────┼────────────┐
           ▼             ▼            ▼
     search_kb    get_flow_guidance  get_customer_profile
     (RAG检索)     (流程指引)         (CRM查询)
```

- **不是多Agent** — 只有一个Agent在推理
- Agent 自主决定是否调用、调用哪些 Skills
- 简单对话直接回复，复杂场景调用Skills获取信息后回复

## 快速启动

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-xxx

# API服务
uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000

# CLI交互
python scripts/dialogue_engine.py

# Docker
docker build -t telesales-dialogue .
docker run -e OPENAI_API_KEY=sk-xxx -p 8000:8000 telesales-dialogue
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions` | 创建会话 |
| POST | `/chat` | 对话（Agent自动调度Skills） |
| GET | `/sessions/{id}` | 会话状态 |
| DELETE | `/sessions/{id}` | 删除会话 |
| GET | `/health` | 健康检查 |

## 测试

```bash
pytest scripts/test_dialogue.py -v
```

## 项目结构

```
├── SKILL.md                         # 架构设计文档
├── scripts/
│   ├── dialogue_engine.py           # 单Agent对话引擎 + Skills实现
│   ├── api_server.py                # FastAPI服务
│   └── test_dialogue.py             # 测试用例
├── references/
│   ├── agent-system-prompt.md       # Agent System Prompt
│   ├── skill-search-kb.md           # 知识检索Skill详设
│   └── flow-nodes.md               # 各流程节点指引内容
└── assets/
    └── flow_graph.json              # 流程图配置（数据驱动）
```
