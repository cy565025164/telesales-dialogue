# Skill: search_kb — 知识检索实现

## 功能
从知识库检索产品信息、价格、政策、异议应对策略等事实性内容。

## 检索架构

```
Agent调用 search_kb(query, category)
        │
        ▼
┌───────────────────┐
│  Query构造        │  query + category → search_text
└───────┬───────────┘
        │
   ┌────┴─────┐
   ▼          ▼
┌────────┐ ┌──────┐
│Embedding│ │BM25  │   双路召回
│ Search  │ │Search│
└───┬────┘ └──┬───┘
    └────┬────┘
         ▼
   ┌──────────┐
   │RRF Merge │   Reciprocal Rank Fusion
   └────┬─────┘
        ▼
   ┌──────────┐
   │ Rerank   │   按category相关性加权
   └────┬─────┘
        ▼
   Top-5 snippets → 返回给Agent
```

## 知识库分类 (category)

| category | 内容 | 示例 |
|----------|------|------|
| product | 产品功能、规格、价格、对比 | "套餐A包含XX功能，月费99元" |
| objection | 异议应对策略和话术参考 | "价格异议：强调ROI和日均成本" |
| policy | 退换货、售后、合规条款 | "7天无理由退货，需保持包装完整" |
| script | 各节点话术模板 | "开场白模板：您好，我是XX公司..." |

## 文档Schema

```json
{
  "id": "doc_001",
  "category": "product",
  "title": "标题",
  "content": "正文内容",
  "tags": ["标签"],
  "metadata": {
    "product_id": "可选",
    "node": "适用的流程节点(可选)",
    "updated_at": "2024-01-01"
  }
}
```

## 合规注入规则

当 category 为 `product`(涉及价格) 或 `policy` 时，自动追加合规免责片段：
```python
if category in ("product", "policy"):
    results.append(get_compliance_disclaimer(category))
```

## 实现接口

```python
async def search_kb(query: str, category: str = "product") -> dict:
    """
    返回: {
        "snippets": ["内容片段1", "内容片段2", ...],
        "sources": ["来源引用1", ...]
    }
    """
```
