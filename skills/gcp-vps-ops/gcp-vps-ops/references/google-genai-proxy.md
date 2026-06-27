# Google GenAI Proxy Development Reference

> Vertex AI ↔ OpenAI 兼容代理的完整开发经验，2026-06-23 验证通过。

## 架构

```
Hermes --[OpenAI protocol]--> vertexai_proxy.py (127.0.0.1:18999) --[google-genai]--> Vertex AI
```

**为什么不改 Hermes 核心**：
- Proxy ~650 行 vs 改 Hermes 核心 ~600+ 行且影响全局
- 独立测试（curl 直接验证），独立重启，独立 debug
- 零核心改动，上游升级无影响

## 4 个核心 Bug 及修复

| # | Bug | 根因 | 修复 |
|---|-----|------|------|
| 1 | Turn N+1 工具调用 400 | Gemini tool result 需 `role: "user"` + `function_response` part | 改为 nanobot 范式 |
| 2 | `parts: []` 空消息 → 400 | Vertex AI 拒绝空 parts | 用 `"."` 占位符 |
| 3 | Gemini 3.x 多轮 tool call 400 | `thought_signature` 双向丢失 | response 捕获 → base64 写 extra_content；request 读回 → 解码塞回 part；加全局 cache 兜底 |
| 4 | 流式 stderr Warning | `chunk.text` getter 有 function_call 时 emit warning | 遍历 `chunk.candidates[0].content.parts` |

## thought_signature 机制

**关键发现**：Gemini 3.x thinking 模型要求 `thought_signature` 在 tool call 下一轮原样回传。

**三方链路**（完整理解后才能调试）：

```
1. Vertex AI response → part.thought_signature (binary bytes)
2. Proxy 捕获 → base64 encode → 塞进 OpenAI tool_call.extra_content.google.thought_signature
3. Hermes 下一轮 → 把 extra_content 原样放回 assistant message 的 tool_calls
4. Proxy 收到 → base64 decode → 塞回 Gemini function_call.thought_signature
5. Vertex AI 验证通过 → 200 OK
```

**Hermes 端的现有支持**（不需要 proxy 做的部分）：
- `run_agent.py:4991 _sanitize_tool_calls_for_strict_api` — 当目标模型是 gemini/gemma 家族时，`extra_content` 在持久化和转发时保留
- `chat_completions.py:102 _model_consumes_thought_signature` — 判断是否需要传给指定 provider

**Proxy 的兜底角色**：即使 Hermes 端丢失 extra_content，proxy 的全局 `_THOUGHT_SIG_CACHE: dict[str, bytes]` 也会自动注入。

## 前缀清洗

上游模型名格式多样：
- `vertexai:gemini-3.5-flash`（冒号分隔）
- `vertexai/gemini-3.5-flash`（斜杠分隔）
- `vertex-ai/gemini-3.5-flash`

Proxy 用 `_PREFIXES = ("vertexai", "vertex", "vertex-ai", "vertexai-genai")` 先按 `:` 再按 `/` 分割，剥离前缀后传给 google-genai。

## 流式 Function Call

```python
accum_args = ""
for chunk in client.models.generate_content_stream(...):
    for part in chunk.candidates[0].content.parts:
        if part.function_call:
            accum_args += part.function_call.args  # 增量 JSON 片段
# 全部拼接完再 json.loads()
```

**避坑**：streaming 中 `part.function_call.args` 是不完整的 JSON 片段，不能逐 chunk parse。

## 代理层设计原则

1. **Proxy > Hermes core** — 模型相关问题优先在代理层修复
2. **独立可测试** — curl 验证后再接入 Hermes
3. **最小化状态** — thought_signature cache 是唯一的必要状态
4. **前缀兼容** — 支持多种 provider 前缀格式
5. **graceful degradation** — compression model 为空时检查 fallback 链末端是否有 ≥64K 模型

## 当前运行状态

- **gcp-vps2**：`systemctl --user` 运行中，PID 958，138.9M RSS
- **instance-20260413-080555**：不跑 proxy，hermes-lite 直连 OpenRouter
- **支持的模型**：gemini-2.5-pro / gemini-3.5-flash / gemini-3.1-flash-lite / gemini-3-flash-preview / gemini-flash-latest

## 相关文件

- Proxy 代码：`~/.hermes/scripts/vertexai_proxy.py`（647 行）
- Systemd unit：`~/.hermes/scripts/vertexai_proxy.service`
- Hermes provider 配置：`~/.hermes/config.yaml` 中的 `custom_providers.vertexai` 块
