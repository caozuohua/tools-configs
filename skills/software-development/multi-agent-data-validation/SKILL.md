---
name: multi-agent-data-validation
description: "多智能体并行校对/清洗数据集的标准化工作流。适用于 JSON 数据质量校验、标签规范化、摘要完整性检查等场景。使用 Hermes delegate_task 并行分发多个校对代理。触发条件：数据校对、数据清洗、批量校验、多智能体协作。"
version: 1.0.0
metadata:
  hermes:
    tags: [multi-agent, data-validation, data-cleaning, parallel, delegate]
---

# 多智能体并行数据校对

## 概述

使用 Hermes `delegate_task` 并行分发多个校对代理，各自负责一批数据的逐条校验。适用于 JSON 数据集的质量修复。

## 触发条件

- 需要批量校对/清洗大量数据条目
- 数据条目可按 ID、国家、时间等维度分片
- 单条数据需要多个字段交叉校验

## 核心工作流

### 1. 数据分片策略

按案例的 ID 前缀（国家代码）分片，每片 30-50 条为佳：

| 代理 | ID 前缀 | 国家 | 典型数量 |
|------|---------|------|---------|
| A1 | cn- | 中国 | 50 |
| A2 | jp-/kr-/in-... | 东亚东南亚 | 24 |
| A3 | iq-/sa-/jo-... | 中东 | 14 |
| B | de-/es-/it-... | 欧洲 | 49 |
| C | us-/br-/co-... | 美洲+非洲+大洋洲 | 55 |

### 2. 校对代理 Prompt 模板

```
你是电力案例校对专家。请对 {data_file} 中 id 以 {prefix_list} 开头的案例进行逐条校对。

校对标准：
1. title 是否准确反映项目实质且不是泛泛2. year 是否在 {year_range} 范围内
3. tech 标签是否都在允许列表中
4. summary 是否达到{min_chars}字以上且包含实质内容
5. confidence 是否合理

操作步骤：
1. read_file 读取 {data_file}
2. 筛选 id 符合条件的案例
3. 逐条检查
4. 将修正建议写入 {output_corrections}
5. 将摘要报告写入 {output_report}

注意：不修改原数据文件，只生成修正建议。
```

### 3. 结果汇总与批量应用

```bash
# 合并所有 corrections
cat data/corrections_batch*.json | python3 -c "
import json, sys
all = []
for line in sys.stdin:
    all.extend(json.loads(line) if line.strip().startswith('[]') else [json.loads(line)])
# ... 合并逻辑
"
```

### 4. 关键参数

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| 每片最大条数 | 30-50 | 超过50条代理可能超时 |
| 超时时间 | 600s | delegate_task 默认超时 |
| 并行数 | ≤3 | Hermes 默认最大并发 |
| 二次拆分阈值 | >600s | 首次超时后拆半 |

## Pitfalls

1. **超时问题**：中国等大国数据量超大（100+条），必须拆分（cn- 单独一批 50 条，不要和其他国家混）
2. **搜索+补充任务**：每个子代理目标 ≤ 5 条新案例，超过 600s 一定超时。分批多次派发。
3. **tech 标签匹配**：子代理返回的 `old` 值可能是 JSON 数组字符串或类型不一致，需精确匹配后替换
4. **summary 修正局限**：子代理没有原始来源 URL，只能给建议，实质性补充需人工回访 source 或从 detail 字段提取
5. **备份优先**：应用修正前先 `cp cases.json cases.json.bak{date}`
6. **增量应用**：先应用 tech/title/confidence 等确定性字段，summary 的补充需人工审核
7. **主会话 web_search 可能失效**：依赖 Nous 订阅额度，额度耗尽后需切到子代理的 browser 工具或 terminal curl
8. **ID 冲突处理**：子代理可能生成与已有案例冲突的 ID，入库前检查并修正（加后缀或改序号）
9. **tech 字段类型**：子代理可能把 tech 写成字符串而非列表，入库前统一 `list(dict.fromkeys(...))`
10. **子代理输出结构不一致**：候选文件可能是 `list`（直接数组）或 `dict`（含 `batch`/`cases` 键），合并前必须探测结构：`data = json.load(f); cases = data if isinstance(data, list) else data.get('cases', [])`
11. **子代理字段名不一致**：部分子代理用中文 key（`"title(中文)"`、`"country(中文国家名)"`），合并时需归一化为标准字段名（`title`、`country`）
12. **子代理脏数据**：可能写入缺少 `id`/`title`/`company` 字段的条目，入库前必须检查并丢弃
13. **cron 模式下 execute_code 被阻止**：定时任务中合并逻辑必须用 `terminal` 运行 python3 脚本，不能用 `execute_code`
14. **子代理全部 ID 冲突不代表失败**：同一批子代理可能搜索相同案例，加后缀后仍可能是有价值的不同角度描述
6. **去重**：tech 字段修正后必须 `list(dict.fromkeys(techs))` 去重
7. **残留分析**：修正后扫描 `all_tags` 确认无违规；对无法映射的标签直接丢弃（如纯公司名、设备型号）

## 技术选择决策

| 场景 | 推荐框架 | 理由 |
|------|---------|------|
| 批量数据校对 | `delegate_task` | 并行、隔离、无推理负担 |
| 需要复杂交互决策 | CrewAI | 角色制对话协作 |
| 需要状态持久化/断点恢复 | LangGraph | Checkpointer + 循环图 |
| Hermes 生态内快速任务 | `execute_code` | 简单直接，无需外部依赖 |

### LLM 摘要/生成 + Fallback 模式

当需要为数据集添加 AI 摘要（文档生成、日报摘要等）时，使用 multi-backend + fallback 模式：

```python
def ai_summarize(items, lang="zh"):
    """调用 LLM 生成中文摘要，fallback 到规则摘要"""
    # ... 构建 prompt ...
    
    try:
        import os
        from openai import OpenAI

        model = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("VERTEXAI_PROXY_KEY")

        if os.environ.get("VERTEXAI_PROXY_URL"):
            # VertexAI 代理（本地/内网）→ 需关闭 thinking
            base_url = os.environ["VERTEXAI_PROXY_URL"]
            model = os.environ.get("LLM_MODEL", "gemini-3.5-flash")
        elif api_key:
            # Google AI Studio 直连（免费，无 thinking 参数）
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        else:
            return _fallback_summary(items)  # 无 key → fallback

        client = OpenAI(base_url=base_url, api_key=api_key)
        
        create_kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.7,
        )
        # ⚠️ 只有 VertexAI 代理才需要/支持 thinking_config
        if "generativelanguage.googleapis.com" not in base_url:
            create_kwargs["extra_body"] = {
                "google": {"thinking_config": {"include_thoughts": False, "thinking_budget": 0}}
            }
        
        resp = client.chat.completions.create(**create_kwargs)
        result_text = resp.choices[0].message.content.strip()
        if result_text:
            return result_text
    except Exception as e:
        print(f"[WARN] LLM 摘要失败({e})，使用规则摘要")
    
    return _fallback_summary(items)  # 任何失败 → fallback
```

## ⚠️ MVP/架构类回答规范

用户偏好：**不要只给骨架代码然后等用户追问**。设计类回答必须包含：
1. 骨架代码（能跑）
2. **生产级差距清单**（缺什么、每项复杂度 ×）
3. **Realistic code estimate**（骨架 + 胶水 ≈ 多少行）
4. 明确的下一步选项（让用户选方向）

反例：77 行 LangGraph MVP → 用户问"就这么少？" → 才补差距清单 ❌
正例：77 行骨架 + 表格列出 8 个缺口 + ~330 行 realistic estimate ✅

## 相关资源

- Hermes delegate_task 文档：`hermes-agent` skill
- 电力案例项目：`power-digital-cases` skill
- LLM 摘要 + Fallback 模式（多后端、429/400 调试）: [references/llm-fallback-pattern.md](references/llm-fallback-pattern.md)
