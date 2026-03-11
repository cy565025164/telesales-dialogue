# Knowledge Base — 知识库设计

## 知识库架构

采用 **混合检索** 策略: 向量语义检索 (Embedding) + 关键词检索 (BM25)，结果融合后Rerank。

```
┌─────────────────────────────────────────┐
│            Knowledge Base               │
├──────────┬──────────┬──────┬────────────┤
│ 产品库    │ 话术库    │异议库 │ 政策库     │
│ products │ scripts  │objections│ policies│
└──────────┴──────────┴──────┴────────────┘
        │                │
        ▼                ▼
  ┌──────────┐    ┌──────────┐
  │ Embedding │    │  BM25    │
  │  Index    │    │  Index   │
  └─────┬────┘    └────┬─────┘
        └──────┬───────┘
               ▼
        ┌──────────┐
        │  Reranker │ (按 node relevance 加权)
        └──────────┘
```

## 文档Schema

### 产品文档
```json
{
  "doc_type": "product",
  "product_id": "string",
  "title": "产品名称",
  "features": ["功能点"],
  "price": { "list": 0, "promo": 0, "unit": "元/月" },
  "comparison": { "competitor": "对比点" },
  "tags": ["标签"],
  "content": "详细描述"
}
```

### 话术文档
```json
{
  "doc_type": "script",
  "node": "流程节点",
  "intent": "适用意图",
  "strategy": "策略标签",
  "template": "话术模板（支持变量替换 {customer_name}）",
  "examples": ["示例话术"],
  "tags": ["标签"]
}
```

### 异议文档
```json
{
  "doc_type": "objection",
  "objection_type": "price|need|timing|trust|competitor",
  "customer_says": "客户原话示例",
  "response_strategy": "应对策略",
  "response_examples": ["回复示例"],
  "do_not": ["禁止话术"]
}
```

### 政策文档
```json
{
  "doc_type": "policy",
  "category": "refund|warranty|delivery|compliance",
  "content": "政策内容",
  "compliance_notes": "合规注意事项"
}
```

## 检索策略

```python
def search(intent: str, node: str, query: str, top_k=5):
    # 1. 构造检索query
    search_query = f"{intent} {node} {query}"

    # 2. 双路召回
    vec_results = embedding_search(search_query, top_k=20)
    bm25_results = bm25_search(search_query, top_k=20)

    # 3. 融合去重 (RRF - Reciprocal Rank Fusion)
    merged = rrf_merge(vec_results, bm25_results)

    # 4. Node相关性加权
    for doc in merged:
        if doc["node"] == node:
            doc["score"] *= 1.5  # 当前节点文档权重提升
        if doc["intent"] == intent:
            doc["score"] *= 1.3  # 意图匹配文档权重提升

    # 5. 合规片段强制注入
    if intent in ["price_inquiry", "policy_ask"]:
        compliance = get_compliance_docs(intent)
        merged = compliance + merged

    # 6. 返回Top-K
    return sorted(merged, key=lambda x: x["score"], reverse=True)[:top_k]
```

## Embedding模型

| 选项 | 推荐 |
|------|------|
| 模型 | text-embedding-3-large |
| 维度 | 1536 |
| 向量库 | Milvus / Qdrant / Weaviate |
| 分块 | 按文档自然边界，每chunk ≤ 512 tokens |
