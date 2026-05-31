---
name: health-hot
description: 查询「查过再信」中文循证健康说法核验库。当用户问某个健康说法是否可信、或某话题最近有什么证据更新时使用。只返回库中已核验内容（结论 / 证据强度 / 适用人群 / 局限 / 原文链接），不提供个体化医疗建议。
---

# health-hot · 查过再信健康核验查询

「查过再信」是一个中文循证健康说法核验库：把流行的健康说法逐条查到原始证据、标出强度、写清适用人群和注意事项。本 Skill 让你（或任何人的 Agent）直接查询它**已核验**的说法。

## 数据源

公开机读 feed，无需鉴权，任何人可匿名抓取：

```
https://liuyuxin01210725-debug.github.io/health-hot/claims.json
```

用网页抓取 / `curl` 取回该 URL，得到如下 JSON：

```jsonc
{
  "schema_version": "1.0",
  "site_url": "https://liuyuxin01210725-debug.github.io/health-hot/",
  "disclaimer": "...",        // 医疗免责，回答时必须随附
  "generated_at": "2026-05-31",
  "count": 22,
  "claims": [
    {
      "slug": "creatine-lipids",
      "title": "说法标题",
      "conclusion": "一句话结论",
      "evidence": "rct|meta|guideline|observational|expert|blogger|anecdote",
      "evidence_label": "RCT|Meta|指南|观察|专家|博主|个例",
      "population": "适用于谁",
      "caveats": "局限 / 需要注意",
      "summary": "详情",
      "category": "运动|营养|睡眠|补剂|心理|…",
      "source_urls": ["原始来源链接（PubMed / 指南等，至少 1 条）"],
      "discovery_source_url": "你可能在哪听到（播客等，非证据，可能为空）",
      "detail_url": "网站详情页 URL",
      "reviewed_at": "本站复核日期"
    }
  ]
}
```

匹配用户问题时，在 `claims` 里按 `title` / `conclusion` / `summary` / `category` 做关键词匹配。

## 工作规则（务必遵守）

1. **查某个说法** —— 找到匹配的 claim，返回：结论、证据强度（`evidence_label`）、适用人群、局限、原始来源。
2. **查最近更新** —— 按 `reviewed_at` 倒序，列出近期复核的条目（标题 + 结论 + 证据强度 + 详情页）。
3. **剂量 / 症状 / 诊断 / 用药调整 类问题** —— 明确说明：本库**不提供个体化医疗建议**，请咨询持证医生或注册营养师。可以转述库里相关说法的**原则性**结论，但**不给**具体克数 / 剂量 / 诊断 / 用药方案。
4. **没有匹配** —— 诚实回答「库中暂无对这条说法的核验」。**绝不**用模型自身知识补一个结论冒充库内容。可建议对方到网站详情页提交想核验的说法。
5. **每条回答都必须保留** `detail_url`（详情页）和至少一个 `source_urls` 链接，让用户能自己回原文核对。

## 输出格式（建议模板）

> **说法**：<用户问的说法>
> **结论**：<conclusion>
> **证据强度**：<evidence_label>
> **适用于谁**：<population>
> **要注意**：<caveats>
> **原文**：<source_urls[0]>　｜　**详情页**：<detail_url>

回答结尾附上 feed 里的 `disclaimer` 原文。

## 边界

- 本 Skill 只读公开核验库，**不**访问任何个人健康数据、体检指标或病史。
- 只呈现库中已核验的内容；库里没有的，就说没有，**不编、不脑补**。
- 非医疗建议；涉及个人执行，一律指向持证医生 / 注册营养师。
