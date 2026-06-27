# 🛠️ tools-configs

自制技能、工具脚本和配置文件集合。

> 这些是日常工作中积累的"基础设施知识"——每一条踩坑记录都对应一次真实的 debug 经历。

## 目录结构

```
tools-configs/
├── skills/              # 自制 Hermes Skills（SKILL.md 格式）
│   ├── software-development/   # 开发流程、代码质量
│   ├── devops/                 # 基础设施、安全、部署
│   ├── mlops/                  # ML 工程、搜索、模型
│   ├── github/                 # GitHub API 操作
│   └── research/               # 研究工具、案例集
├── scripts/             # 自制 Python 脚本
│   ├── vertexai_proxy.py       # VertexAI → OpenAI 代理
│   ├── vertex_gemini.py        # Gemini API 直接调用
│   └── vps-watchdog.py         # VPS 监控
├── configs/             # 配置文件模板
│   ├── vertexai-proxy.yaml     # VertexAI 代理配置
│   └── config.yaml             # Hermes 配置模板
└── references/          # 参考文档、API 规范
```

## Skills 清单

### 开发流程
| Skill | 用途 |
|-------|------|
| `markdown-to-html-email` | LLM Markdown → 邮件 HTML 排版（列表/标题/段落） |
| `multi-agent-data-validation` | 多智能体并行校对数据集 |
| `static-data-scaffold` | JSON 数据驱动静态站点脚手架 |
| `hermes-provider-integration` | 接入新 LLM Provider 到 Hermes |
| `hermes-agent-skill-authoring` | 编写高质量 SKILL.md 的规范 |
| `llm-agent-execution-patterns` | 诊断 LLM Agent "只说不做"问题 |
| `agent-framework-design-analysis` | 分析框架设计模式并提取可迁移经验 |
| `incremental-audit-and-fix` | 逐文件审计 + 单任务修复工作流 |
| `subagent-driven-development` | 子代理驱动的开发计划执行 |
| `systematic-debugging` | 4 阶段根因调试法 |
| `python-oss-readiness` | Python 项目开源发布检查 |
| `test-driven-development` | TDD 红绿重构 |
| `verification-before-completion` | 完成前验证（先跑命令再声称完成） |

### DevOps & 基础设施
| Skill | 用途 |
|-------|------|
| `hermes-vertexai-provider` | VertexAI 代理中间件完整配置 |
| `hermes-multi-profile` | Hermes 多 profile 诊断 |
| `cloudflare-vps-edge-protection` | Cloudflare Access + Tunnel 加固 VPS |
| `headless-google-oauth` | 无浏览器环境 Google API 认证 |
| `x-ui-and-new-api-security-posture` | x-ui + new-api 安全加固 |
| `xray-reality-deployment` | VLESS + Reality 代理部署 |
| `nanobot-vps-deployment` | Nanobot VPS 部署 |
| `gcp-vps-ops` | GCP VPS 运维 |

### MLOps & 搜索
| Skill | 用途 |
|-------|------|
| `gcp-google-search-via-genai` | 通过 VertexAI 代理调用 Google Search |
| `google-genai-python-sdk` | google-genai SDK 全流程配置 |

### GitHub
| Skill | 用途 |
|-------|------|
| `github-workflow-file-update` | GitHub Actions workflow 文件 API 更新 |

### 研究 & 案例
| Skill | 用途 |
|-------|------|
| `mem0-research` | Mem0 记忆层调研 |
| `power-digital-cases` | 电力行业数字化案例集维护 |

## Scripts 清单

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `vertexai_proxy.py` | VertexAI → OpenAI 兼容代理 | google-cloud-aiplatform |
| `vertex_gemini.py` | Gemini API 直接调用示例 | google-genai |
| `vps-watchdog.py` | VPS 健康监控 | requests |

## 快速开始

### 启动 VertexAI 代理
```bash
cd tools-configs
pip install google-cloud-aiplatform
python scripts/vertexai_proxy.py
# 代理监听 127.0.0.1:18999
```

### 使用技能
```bash
# 将 skill 复制到 Hermes skills 目录
cp -r skills/markdown-to-html-email ~/.hermes/skills/software-development/
```

## 维护

- Skills 更新: 编辑 `skills/` 下的 SKILL.md，同步到 `~/.hermes/skills/`
- 新工具: 放入 `scripts/`，添加 shebang + chmod +x
- 新配置模板: 放入 `configs/`

---

*这些工具都是在真实项目中反复打磨出来的——不是 demo，是生产代码。*
