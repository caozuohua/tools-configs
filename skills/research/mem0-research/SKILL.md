# Mem0 调研报告

## 概述

**Mem0** 是一个开源的 AI Agent 记忆层（Memory Layer），YC S24 支持，定位为"AI 的个人化记忆引擎"。2026年4月发布全新记忆算法，benchmark 分数大幅提升。

**官网**: https://mem0.ai | **GitHub**: https://github.com/mem0ai/mem0 | **文档**: https://docs.mem0.ai

## 核心能力

### 多层级记忆
- **User Memory**: 用户偏好、历史行为（跨会话持久化）
- **Session Memory**: 当前对话上下文
- **Agent Memory**: Agent 自身的状态和知识

### 知识图谱 + 向量检索混合架构
- **向量检索**（语义相似度）：默认 text-embedding-3-small
- **BM25 关键词匹配**：精确关键词命中
- **实体链接**（Entity Linking）：跨记忆的实体关联增强
- **时间感知检索**：区分当前状态、过去事件、未来计划

### 2026年4月新算法 (v3)
| Benchmark | 旧版 | 新版 | Tokens | 延迟 |
|-----------|------|------|--------|------|
| LoCoMo | 71.4 | **91.6** | 7.0K | 0.88s |
| LongMemEval | 67.8 | **94.8** | 6.8K | 1.09s |
| BEAM (1M) | — | **64.1** | 6.7K | 1.00s |
| BEAM (10M) | — | **48.6** | 6.9K | 1.05s |

关键改进：
- 单次 ADD-only 提取（一次 LLM 调用，无 UPDATE/DELETE）
- Agent 确认的事实作为一等公民存储
- 多信号检索融合（语义 + BM25 + 实体）

## 部署模式

| 模式 | 适用场景 | 安装方式 |
|------|---------|---------|
| **Library (pip/npm)** | 原型开发/测试 | `pip install mem0ai` 或 `npm install mem0ai` |
| **Self-Hosted** | 团队自有基础设施 | `cd server && make bootstrap` (Docker Compose) |
| **Cloud Platform** | 零运维生产 | app.mem0.ai 注册即用 |

### Self-Hosted 架构
```
Client → mem0 FastAPI Server → Vector DB (Qdrant)
                              → PostgreSQL (元数据/用户/配置)
                              → Embedding Model (text-embedding-3-small / Qwen 600M)
                              → Cache (可选)
                              → Message Queue (可选，异步嵌入)
```

## 集成生态

- **LangGraph**: 客服机器人
- **CrewAI**: 多智能体协作记忆
- **Claude Code / Codex / Cursor / Windsurf / OpenCode / OpenClaw**: Agent Skills
- **Vercel AI SDK**: 官方集成
- **Chrome 扩展**: 跨 ChatGPT/Perplexity/Claude 记忆

## API 示例

```python
from mem0 import Memory

memory = Memory()

# 添加记忆
memory.add(messages, user_id="alice")

# 搜索记忆
results = memory.search(query="用户偏好", filters={"user_id": "alice"}, top_k=3)

# 更新记忆
memory.update(memory_id="xxx", data="新信息")

# 获取全部
memory.get_all(user_id="alice")
```

## 竞品对比

| 维度 | Mem0 | Zep | LangChain Memory |
|------|------|-----|-----------------|
| 定位 | 专用记忆层 | 生产级长期记忆 | 抽象层 |
| 架构 | 知识图谱+向量+BM25 | 向量+自动提取 | 多种后端可选 |
| 自托管 | ✅ Docker Compose | ✅ | 需自建 |
| 云托管 | ✅ 免费开发层 | ✅ | ❌ |
| 多模态 | 文本为主 | 文本+图片 | 框架支持 |
| 实体链接 | ✅ | ❌ | ❌ |
| 时间感知 | ✅ | ❌ | ❌ |
| 延迟 | ~1s | ~1-2s | 取决于后端 |
| 适合 | 个人化AI助手 | 企业级对话历史 | LangChain生态 |

## 与 Hermes 的关联

Hermes 已有内置的 `memory` 工具（持久化记忆）和 `session_search`（历史会话搜索）。Mem0 的定位更偏向：
1. **用户级个性化记忆**（跨用户隔离的长期偏好）
2. **Agent 状态管理**（多智能体场景的状态共享）
3. **知识图谱增强**（实体关系网络）

**结论**: Mem0 适合作为 Hermes 的**增强层**（非替换），在以下场景使用：
- 需要跨用户隔离的个性化记忆
- 需要实体级记忆而非文档级
- 需要时间序列记忆（"上次是什么时候"）

**不建议替换 Hermes 内置 memory**，因为 Hermes memory 是 key-value 持久化（用户画像/环境），而 Mem0 是语义检索层（对话/知识）。两者互补。
