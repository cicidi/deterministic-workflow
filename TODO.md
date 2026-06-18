# TODO — Deterministic Workflow Framework

Last updated: 2026-06-17

---

## Skills — Done

| Skill | 说明 |
|-------|------|
| ✅ **issue-create** | 从 spec 讨论生成结构化 GitHub issue |
| ✅ **implement-interview** | 访谈式加载 11 篇 spec，产出产品级 implement plan |
| ✅ **evals-create** | 生成 goal definition + goal check eval + response eval + intent eval + decision eval |
| ✅ **ai-cowork-install** | 安装配置 ai-coworker，注册 MCP server，sync 到所有 AI 工具 |

---

## Skills — Planned

| Skill | 说明 | 优先级 |
|-------|------|--------|
| 🔲 **intent-analysis** | 分析 prod log，发现未处理 intent，生成 gap report。原则：今天比昨天好 | P0 |
| 🔲 **tdd** | 先定义 test case（用户对话、extract node、validate node、decision node、response node）、mock LLM 省 token | P0 |
| 🔲 **test-client-create** | 模拟 LLM test client 和 agent 对话，测量 complete transaction rate | P1 |
| 🔲 **code-gen** | 从 implement plan 产出 Python 代码（参考 CrewAI 的 4 个 coding skills） | P1 |
| 🔲 **spec-generator** | 加载 11 篇 framework spec → 问答式帮助 developer 产出产品级 spec（VISION.md 的核心愿景） | P0 |
| 🔲 **ask-docs** | MCP server 实时查最新 spec API（类似 CrewAI 的 ask-docs skill） | P2 |
| 🔲 **crewai-adaptor** | 让我们的 workflow 能作为 CrewAI Flow/Crew 的一步运行，互相调用 | P1 |
| 🔲 **history-labeler** | 基于 history turns，正确处理的标记为 positive example，错误的标记为 negative，生成训练/测试数据集。可用现成框架：**Argilla**（数据标注平台）、**Label Studio** | P1 |
| 🔲 **multi-llm-runner** | 跑测试集同时对比多个 LLM（如 `deepseek-v4 / gpt-4o / claude-sonnet`），输出侧对比准确率；同时测试 client-side LLM 能否正确理解我们的 response。可用现成框架：**promptfoo**（多 LLM 对比测试）、**DeepEval**（指标化评估）、**RAGAS**（RAG 场景评估） | P1 |

---

## Spec Documents — Done

| # | Spec | Version |
|---|------|---------|
| 1 | [HLD](docs/specs/2026-06-16-deterministic-workflow-framework-design.md) | v0.7.0 |
| 2 | [Intent Classification](docs/specs/2026-06-16-intent-classification-design.md) | v0.3.0 |
| 3 | [State Machine](docs/specs/2026-06-16-state-machine-design.md) | v0.6.0 |
| 4 | [Extraction Layer](docs/specs/2026-06-17-extraction-layer-design.md) | v0.4.0 |
| 5 | [Domain Model](docs/specs/2026-06-17-domain-model-design.md) | v0.3.0 |
| 6 | [Routing & Execution](docs/specs/2026-06-17-routing-execution-layer-design.md) | v0.3.0 |
| 7 | [Response Generation](docs/specs/2026-06-17-response-generation-layer-design.md) | v0.4.0 |
| 8 | [LLM Gateway](docs/specs/2026-06-17-llm-gateway.md) | v0.1.0 |
| 9 | [Tool Ecosystem](docs/specs/2026-06-17-tool-ecosystem.md) | v0.3.0 |
| 10 | [Environment Config](docs/specs/2026-06-17-environment-config.md) | v0.3.0 |
| 11 | [Auth & Token Verification](docs/specs/2026-06-17-auth-token-verification.md) | v0.2.0 |

## Spec Documents — Planned

| # | Spec | Status | 说明 |
|---|------|--------|------|
| 12 | MCP API Protocol | 🔲 draft v0.1 | Framework API via MCP, compatible with Claude/OpenAI/Google |
| 13 | Conversation Lifecycle | 🔲 draft v0.1 | create/active/paused/resume/timeout, trace_id=user_id |
| 14 | Observability & Monitoring | 🔲 draft v0.1 | Grafana dashboards, Prometheus metrics, alert rules |
| 15 | CI/CD (Jenkins) | 🔲 draft v0.1 | Jenkins pipeline, eval→deploy, mrratequote chat example |
| 16 | A2A Protocol | 🔲 draft v0.1 | Agent-to-Agent communication, sub-workflow = A2A |
| 17 | Rate Limiting | 🔲 draft v0.1 | per-user/per-tenant/per-tool, interview integration |
| 18 | Widget Templates | 🔲 draft v0.1 | A2A chatbot template + Claude-generated widgets for mrratequote |

---

## Future Work

- [ ] **CrewAI Compatibility** — Export domain model → CrewAI config. Register pipeline as CrewAI tool. Mutual invocation between our deterministic sub-workflow and CrewAI Crew.
- [ ] RoleResolver implementation (Auth spec §5.1 interface placeholder)
- [ ] Python reference implementation
- [ ] LangFlow custom components for framework nodes
- [ ] `agentState` reducer conflict detection for async sub-workflow + parent concurrent writes
- [ ] Token refresh support for long-running conversations
