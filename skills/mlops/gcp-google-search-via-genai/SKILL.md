---
name: gcp-google-search-via-genai
description: "通过本地 VertexAI 代理调用 Google Search (gemini google_search tool)，利用 GCP 赠金做联网搜索的经验。适用于 web_search额度耗尽时的替代方案。触发条件：联网搜索、web_search不可用、需要实时信息。"
version: 1.0.0
metadata:
  hermes:
    tags: [gcp, google-search, genai, vertexai, web-search]
---

# GCP Google Search 替代方案 (via VertexAI Proxy + google-genai SDK)

## 背景

- Hermes 的 `web_search` / `web_extract` 使用 Nous 管理的 Firecrawl
- 当 Nous Portal 账户额度耗尽后这两个工具完全不可用
- 但我们有 GCP 账户 + Vertex AI 代理（本地 :18999），可以通过 `google-genai` SDK 调用 Gemini 的 `google_search` tool

## 前置条件

1. VertexAI 代理运行中: `http://127.0.0.1:18999/v1`
2. VertexAI 代理至少有一个支持 grounding/search 的模型: `gemini-2.5-flash`
3. 环境变量: `VERTEXAI_PROXY_KEY` (非空即可)
4. Python 包: `google-genai >= 1.0.0`

**费用**: 通过 Vertex AI 代理 → 消耗 GCP 赠金（Gemini API 计费），不走 Nous

## 核心实现

```python
import os, json, urllib.request
from google import genai
from google.genai import types

# ----- 方案1: 直连 Google API (需要 GCP 凭据) -----
client = genai.Client()  # 自动读 GOOGLE_APPLICATION_CREDENTIALS

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents="搜索Query",
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
)

# 获取 AI 综合回答
print(response.text)

# 获取搜索来源
grounding = response.candidates[0].grounding_metadata
if grounding and grounding.grounding_chunks:
    for chunk in grounding.grounding_chunks:
        if chunk.web:
            print(f"  [{chunk.web.title}]({chunk.web.uri})")
```

```python
# ----- 方案2: 通过本地 VertexAI 代理 (无需 GCP credentials) -----
PROXY = "http://127.0.0.1:18999/v1"
KEY = os.environ.get("VERTEXAI_PROXY_KEY", "placeholder")

def search(query, model="gemini-2.5-flash"):
    """通过 Hermes 的 VertexAI 代理调用 Google Search"""
    import xml.etree.ElementTree as ET
    
    url = f"{PROXY}/chat/completions"
    
    # 构造 OpenAI-compatible + google_search tool
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "tools": [{"google_search": {}}],      # 关键：开启 Google Search
        "temperature": 0.7,
        "max_tokens": 4096
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KEY}"
        }
    )
    
    with urllib.request.urlopen(req, timeout=40) as resp:
        result = json.loads(resp.read().decode())
    
    # 从 OpenAI 兼容格式提取
    choices = result.get("choices", [])
    if not choices:
        return {"text": "", "sources": []}
    
    msg = choices[0].get("message", {})
    text = msg.get("content", "")
    
    # 提取搜索来源 (grounding metadata)
    sources = []
    # 注意：部分代理版本可能不返回 grounding
    try:
        gm = choices[0].get("grounding_metadata", {})
        if gm:
            for chunk in gm.get("grounding_chunks", []):
                web = chunk.get("web", {})
                if web:
                    sources.append({
                        "title": web.get("title", ""),
                        "uri": web.get("uri", "")
                    })
    except:
        pass  # 代理兼容性问题可忽略
    
    return {"text": text, "sources": sources}
```

### 已知限制与 Pitfalls

1. **代理兼容性**： `/v1/chat/completions` 端点需要 OpenAI-compatible 格式，但 `google_search` tool 可能需要 Gemini API 原生格式。测试时注意检查 `tools` 字段是否被正确传递。

2. **grounding metadata 不保证返回**：即使搜索成功，部分代理版本可能不返回 grounding_chunks。这种情况下需要从模型输出文本中提取 URL/信息。

3. **配额消耗**：通过 Vertex AI 代理调用 Gemini API 仍消耗 GCP 赠金，比直连 Google API 费率可能略高（取决于代理收费策略）。

4. **替代方案 - gcloud auth print-access-token + API Key**：如果 SDK 方案不可用，可用 `gcloud auth print-access-token` 获取 token，加上 Custom Search API Key 直接 curl Google Custom Search API（需要 API Key + 搜索引擎 ID）。

5. **模型选择**：只有 Gemini 2.0+ 模型支持 search tool：
   - `gemini-2.5-flash` ✅ (推荐)
   - `gemini-2.5-pro` ✅
   - `gemini-3-flash-preview` ✅
   - `gemini-flash-latest` ✅

## 何时使用

| 场景 | 推荐方案 |
|------|---------|
| 搜索具体事实/数据 | GCP Google (genai) ✅ |
| 搜索近期新闻 | GCP Google (genai) ✅ |
| 已有网页 URL 需要内容 | curl web_fetch 直抓 ✅ |
| 行业分析/报告 | GCP Google + grounding ✅ |
| 机构网站爬取 | curl + User-Agent header ✅ |
| web_search 可用时 | 优先用 web_search (更快更便宜) |

## 与 Firecrawl 对比

| 维度 | web_search (Firecrawl) | Google (genai google_search) |
|------|----------------------|------------------------------|
| 提供商 | Nous Firecrawl | Google Gemini API |
| 免费额度 | 依赖 Nous Portal | GCP $300 Free Trial / Always-free |
| 速度 | 快 | 快 |
| 质量 | 网页直搜 | AI综合答案 + 来源链接 |
| grounding | web_extract 单独取 | 自动返回搜索来源 |
| 适合 | 批量爬取 | 搜索+综合答案 |
| 是否可用 | ✅（需额度） | ✅（需 GCP 赠金） |

## 通过 OpenAI 兼容 API 调用 Gemini (非搜索场景)

VertexAI 代理也支持 OpenAI-compatible `/v1/chat/completions` 端点，可用于通用 LLM 调用（摘要、分类等）：

```python
from openai import OpenAI
import os

client = OpenAI(
    base_url=os.environ.get("VERTEXAI_PROXY_URL", "http://127.0.0.1:18999/v1"),
    api_key=os.environ.get("VERTEXAI_PROXY_KEY", "placeholder")
)

resp = client.chat.completions.create(
    model="gemini-3.5-flash",  # 或 gemini-3.1-flash-lite, gemini-2.5-pro
    messages=[{"role": "user", "content": "你的prompt"}],
    max_tokens=2048,
    extra_body={"google": {"thinking_config": {"include_thoughts": False, "thinking_budget": 0}}}
)
print(resp.choices[0].message.content)
```

### ⚠️ Gemini 免费配额管理

Google AI Studio 免费层按模型独立配额。`gemini-2.0-flash` 在频繁测试后容易触发 429 `RESOURCE_EXHAUSTED`：
- `GenerateRequestsPerDayPerProjectPerModel-FreeTier` — 每日请求上限
- `GenerateContentInputTokensPerModelPerMinute-FreeTier` — 每分钟 token 上限

**推荐策略**：
- 开发测试期间用 `gemini-3.1-flash-lite`（独立配额，不容易被耗尽）
- 生产环境（如 GitHub Actions 定时任务）也建议用 `gemini-3.1-flash-lite`
- 如果遇到 429：等几分钟重试 或 切换模型（不同模型的配额独立计算）

### ⚠️ 关键：关闭 Thinking 模式

Gemini 3.x Flash/Pro 默认开启 **thinking**（内部推理），会消耗大量 token 导致 `finish_reason: 'length'` 但返回空内容。**必须**传递 `extra_body` 关闭：
- `thinking_budget: 0` — 彻底关闭（推荐，省 token）
- `include_thoughts: False` — 不包含思考过程

### ⚠️ 关键：Google AI Studio 直连 vs VertexAI 代理的参数差异

**Google AI Studio 直连** (`base_url = "https://generativelanguage.googleapis.com/v1beta"`)：
- ❌ **不支持** `extra_body={"google": {"thinking_config": ...}}` → 返回 400 `Invalid JSON payload received. Unknown name "google"`
- ✅ 不传 `extra_body` 即可（直连默认不开启 thinking）
- ✅ 使用标准 OpenAI SDK `chat.completions.create()` 格式

**VertexAI 代理** (`base_url = "http://127.0.0.1:18999/v1"`)：
- ✅ **必须**传 `extra_body` 关闭 thinking，否则返回空内容
- ✅ 支持 Gemini 特有参数

**正确代码模式（多后端兼容 — 用于 GitHub Actions 等定时任务）**：
```python
import os
from openai import OpenAI

# 自动检测后端
if os.environ.get("VERTEXAI_PROXY_URL"):
    base_url = os.environ["VERTEXAI_PROXY_URL"]  # 本地/内网
    model = os.environ.get("LLM_MODEL", "gemini-3.5-flash")
    api_key = os.environ.get("VERTEXAI_PROXY_KEY", "placeholder")
elif os.environ.get("GOOGLE_API_KEY"):
    base_url = "https://generativelanguage.googleapis.com/v1beta"  # 直连
    model = os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite")
    api_key = os.environ["GOOGLE_API_KEY"]
else:
    print("[WARN] 未配置 LLM 后端，使用 fallback")
    return fallback_response()

client = OpenAI(base_url=base_url, api_key=api_key)

create_kwargs = dict(
    model=model,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=2048,
    temperature=0.7,
)
# 只有 VertexAI 代理才支持 Gemini thinking 配置
# Google AI Studio 直连传此参数 → 400 Invalid JSON payload "Unknown name 'google'"
if "generativelanguage.googleapis.com" not in base_url:
    create_kwargs["extra_body"] = {
        "google": {"thinking_config": {"include_thoughts": False, "thinking_budget": 0}}
    }

resp = client.chat.completions.create(**create_kwargs)
result_text = resp.choices[0].message.content.strip()
if not result_text:
    print(f"[WARN] LLM 返回空内容 (finish_reason={resp.choices[0].finish_reason})")
```

### 可用模型列表

| 模型 | 速度 | 质量 | 适用 |
|------|------|------|------|
| gemini-3.1-flash-lite | 最快 | 一般 | 简单分类/格式化 |
| gemini-3.5-flash | 快 | 好 | 摘要/生成（推荐默认） |
| gemini-2.5-pro | 中 | 最好 | 复杂推理/分析 |

## 相关配置

- Vertex AI 代理配置: Hermes config.yaml 中的 `custom_providers.vertexai`
- Proxy 进程: `http://127.0.0.1:18999` localhost
- GitHub workflow 文件更新技巧（token scope、curl 方法）: [references/github-workflow-file-update.md](references/github-workflow-file-update.md)
- Markdown→HTML 邮件渲染模式（逐行解析、列表/标题/段落分层）: [references/markdown-to-html-email-rendering.md](references/markdown-to-html-email-rendering.md)
