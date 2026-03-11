# 电话销售AI多Agent对话系统

基于 GPT-5 的多Agent协作电话销售对话管理系统。

## 架构

```
用户输入 → Intent Agent → Router Agent → Knowledge Agent → Speech Agent → 话术输出
```

4个核心Agent：
- **Intent Agent** — 意图识别 + 情绪分析
- **Router Agent** — 流程节点路由（硬规则 + LLM推理）
- **Knowledge Agent** — RAG混合检索
- **Speech Agent** — 话术生成（≤80字，含推进动作）

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 设置 OpenAI API Key
export OPENAI_API_KEY=sk-xxx

# 启动API服务
uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000

# 或使用Docker
docker build -t telesales-dialogue .
docker run -e OPENAI_API_KEY=sk-xxx -p 8000:8000 telesales-dialogue
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions` | 创建对话会话 |
| POST | `/chat` | 发送消息获取话术回复 |
| GET | `/sessions/{id}` | 查询会话状态 |
| DELETE | `/sessions/{id}` | 删除会话 |
| GET | `/health` | 健康检查 |

### 示例

```bash
# 创建会话
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "张三"}'

# 对话
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "xxx", "user_input": "你好"}'
```

## 测试

```bash
pytest scripts/test_dialogue.py -v
```

## 项目结构

```
├── SKILL.md                    # 架构设计文档
├── Dockerfile                  # Docker部署
├── requirements.txt            # Python依赖
├── scripts/
│   ├── dialogue_engine.py      # 对话引擎（4 Agent编排）
│   ├── api_server.py           # FastAPI服务
│   └── test_dialogue.py        # 测试用例
├── references/
│   ├── intent-agent.md         # Intent Agent Prompt
│   ├── router-agent.md         # Router Agent 路由规则
│   ├── speech-agent.md         # Speech Agent 话术模板
│   └── knowledge-base.md       # 知识库Schema
└── assets/
    └── flow_graph.json         # 流程图配置
```
