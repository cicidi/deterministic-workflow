# 工具生态集成

> 属于 [确定性工作流框架 — 高层设计](./2026-06-16-deterministic-workflow-framework-design.md)
> 涵盖：可视化编辑器、图调试器、规则引擎、MCP 服务器，以及所有与框架集成的第三方工具。

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|---------|---------|
| 2026-06-17 | 0.1.0 | 工具生态规范初稿 |
| 2026-06-17 | 0.2.0 | 用 YAML 配置示例替换 Python 代码块；新增 errorNode 失败路由（第 6.4 节）；新增开放问题（第 12 节） |
| 2026-06-17 | 0.3.0 | 第 2.2 节 LangFlow 映射表：将 "Error Handler" 改为 "ErrorNode" 以匹配框架术语 |
| 2026-06-18 | 0.4.0 | 修复 §7–§10 子节的章节编号；在 LangFlow 映射表中将 ErrorNode 改为 errorNode（驼峰命名） |
| 2026-06-18 | 0.5.0 | 添加 `a2a` 工具类型（§7.5）：节点可将其他 agent 作为工具通过 A2A 协议调用；添加 `sdk` 工具类型（§7.6）：节点可将 OpenCode/Claude SDK 作为工具 |
| 2026-06-18 | 0.5.1 | 精简 §8 PII 检测：改为工具目录条目 + 交叉引用权威的 [Response Generation §8](./2026-06-17-response-generation-layer-design.md)；同步 a2a-protocol.md 与 mcp-api-protocol.md 的交叉引用 |

---

## 1. 工具栈概览

```
┌─────────────────────────────────────────────────────────────┐
│                    开发者工作流                                │
├───────────────┬───────────────────┬─────────────────────────┤
│   设计        │   调试 / 测试      │   部署 / 监控            │
├───────────────┼───────────────────┼─────────────────────────┤
│  LangFlow     │  LangGraph CLI    │  LangSmith Studio       │
│  (拖拽式      │  (图视图 +        │  (追踪、评估、          │
│   可视化编辑)  │   热重载)          │   提示词工程)            │
├───────────────┴───────────────────┴─────────────────────────┤
│                    运行时引擎                                  │
├───────────────┬───────────────────┬─────────────────────────┤
│  LangGraph    │  规则引擎          │  工具服务器              │
│  (状态图      │  durable_rules    │  MCP 服务器              │
│   执行)        │  business-rules   │  API 端点                │
│               │  pyknow           │  Claude Desktop          │
├───────────────┴───────────────────┴─────────────────────────┤
│                    确定性框架                                  │
│  (领域模型、提取、路由、响应、权限)                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 工具分类

| 类别 | 工具 | 用途 |
|----------|-------|---------|
| **可视化编辑器** | LangFlow | 拖拽式图构建、节点配置 |
| **开发服务器** | LangGraph CLI (`langgraph dev`) | 本地开发，支持热重载 + 图可视化 |
| **调试与监控** | LangSmith Studio | 追踪执行、时间旅行调试、评估数据集 |
| **状态机** | `transitions` | 确定性 FSM 定义 + Graphviz 导出 |
| **图运行时** | LangGraph | 状态图执行、检查点、流式传输 |
| **规则引擎** | durable_rules、business-rules、pyknow | 验证 + 决策规则 |
| **工具服务器** | MCP 服务器、REST API、CLI 命令 | 外部能力集成 |
| **LLM 提供商** | OpenAI、Anthropic (Claude)、本地模型 | NLU、提取、响应生成 |
| **PII 检测** | Presidio、spaCy、自定义 NER | 敏感数据检测、脱敏 |

---

## 2. LangFlow — 可视化编辑器

### 2.1 角色

LangGraph 工作流的拖拽式可视化构建器。开发者可以：
- 可视化设计图拓扑（节点 + 边）
- 配置节点参数（状态、策略、权限）
- 导出为 LangGraph 图代码或 JSON
- 在 Playground 中交互式测试

### 2.2 与我们的框架集成

```
LangFlow UI
    │
    │  拖拽节点：extract、validate、transform、decide、respond
    │  配置：strategy、retry、permission、tool allowlist
    │
    ▼
导出为 YAML → domain_model.yaml + workflow.yaml
    │
    ▼
我们的框架加载 YAML → 生成 LangGraph 图
```

**节点面板映射：**

| LangFlow 节点类型 | 框架接口 | 可在其中配置 |
|--------------------|--------------------|-----------------|
| `Extract` | `ExtractionNode` | extract_strategy、extract_rules |
| `Validate` | `ValidationNode` | validate_strategy、validation_rules |
| `Transform` | `TransformNode` | transform_strategy、transform_rules |
| `Code Executor` | `CodeExecutor` | execute 函数、输入/输出模式 |
| `Decision` | `DecisionNode` | 规则引擎、LLM 回退 |
| `Sub-Workflow` | `SubWorkflowInvoker` | sub_workflow 名称、同步/异步、input_mapping |
| `Respond` | `ResponseGenerator` | response_strategy（pure_message / widget） |
| `ErrorNode` | `ErrorNode` | 策略（clarify / escalate / terminate） |

### 2.3 安装

```bash
pip install langflow
langflow run
# → http://localhost:7860
```

### 2.4 LangFlow 自定义组件

通过 YAML 将框架节点注册为 LangFlow 自定义组件：

```yaml
# langflow_components/extract_node.yaml
name: ExtractEntity
display_name: "Extract Entity"
description: "Extract structured entities from user input"
icon: Search
category: DeterministicWorkflow

parameters:
  - name: strategy
    display_name: "Strategy"
    type: dropdown
    options: [llm_primary, deterministic, hybrid]
    default: hybrid
  - name: entity
    display_name: "Entity"
    type: str
    info: "Domain model entity name"
  - name: state_hint
    display_name: "State Hint"
    type: text
    multiline: true

outputs:
  - name: message
    type: Message
    description: "Extracted entity data"
```

---

## 3. LangGraph CLI — 开发服务器

### 3.1 角色

本地开发服务器，支持热重载和内置图可视化。`langgraph dev` 命令启动一个托管 LangGraph 图的 API 服务器，并提供基于浏览器的 UI，显示：
- 图拓扑（节点 + 边）
- 每个节点的当前状态
- 执行流追踪

### 3.2 集成

```bash
# 使用我们的框架图启动开发服务器
langgraph dev --config langgraph.json
```

```json
// langgraph.json
{
  "dependencies": ["langchain_openai", "./deterministic_workflow"],
  "graphs": {
    "home_insurance_quote": "./deterministic_workflow/graph.py:build_graph"
  },
  "env": "./.env"
}
```

`build_graph` 入口点从 YAML 加载配置并编译 LangGraph `StateGraph`：

```yaml
# deterministic_workflow/config.yaml — 引擎启动配置
engine:
  domain_model: "domain-models/home-insurance.yaml"
  workflow_config: "workflows/home_insurance_quote.yaml"
  checkpoint_backend: "postgresql://localhost:5432/langgraph"
  rule_engine: durable_rules

langgraph:
  entry_point: "deterministic_workflow.graph:build_graph"
  # build_graph() 读取引擎配置，创建 WorkflowEngine，返回编译后的图
```

### 3.3 能力

| 功能 | 命令 / API |
|---------|--------------|
| 启动开发服务器 | `langgraph dev` |
| 文件变更时热重载 | 默认（监视模式） |
| 查看图 | 浏览器访问 `http://localhost:2024` |
| 测试对话 | 内置聊天 UI |
| 检查状态 | 点击任意节点查看状态快照 |
| 时间旅行 | 从任意检查点回放 |
| 部署到 Docker | `langgraph build -t myimage` |

---

## 4. LangSmith Studio — 调试与监控

### 4.1 角色

基于云的 IDE，用于调试、测试和监控 LangGraph Agent。功能包括：
- 执行追踪，含节点级详情
- 时间旅行调试（从任意检查点回放）
- 评估数据集管理
- 提示词工程 Playground
- 一键部署

### 4.2 集成

```yaml
# framework.yaml — LangSmith 追踪配置
langsmith:
  api_key: "${LANGSMITH_API_KEY}"
  tracing: true
  project: "home-insurance-quote"
  # 框架自动追踪所有 LLM 调用和图执行。
  # 每次 conversation.send() 都会在 LangSmith Studio 中创建一条追踪。
```

### 4.3 评估集成

对我们的工作流运行评估数据集，以验证目标检查准确性和响应质量：

```yaml
# langsmith/eval_config.yaml
evaluators:
  - goal_completion_accuracy
  - response_pii_leakage
  - decision_correctness

dataset: "home-insurance-eval-dataset"

experiment:
  name: "home-insurance-v1.0"
  description: "Baseline eval for home insurance quote workflow"
  metadata:
    domain: home_insurance
    version: "1.0.0"

# 运行方式：langsmith eval run --config langsmith/eval_config.yaml
```

---

## 5. 规则引擎

### 5.1 角色

三个可插拔的规则引擎，用于验证和决策节点：

| 引擎 | 安装 | 最适合场景 |
|--------|---------|----------|
| `durable_rules` | `pip install durable-rules` | When/then 推理、跨字段规则 |
| `business-rules` | `pip install business-rules` | 简单的 YAML/JSON 规则，无推理 |
| `pyknow` | `pip install pyknow` | 专家系统、Fact/KnowledgeEngine |

### 5.2 配置

```yaml
# workflow.yaml
nodes:
  validate_property_info:
    rule_engine: durable_rules    # 按节点覆盖

# framework.yaml（全局默认值）
rule_engine:
  default: durable_rules
  available: [durable_rules, business-rules, pyknow]
```

### 5.3 自定义规则引擎注册

通过 YAML 配置注册自定义规则引擎：

```yaml
# framework.yaml
rule_engine:
  default: durable_rules
  available:
    - durable_rules
    - business-rules
    - pyknow
    - custom_engine:
        module: "my_package.custom_rules"
        class: "CustomRuleEngine"
        # 必须实现：compile(ruleset_name, rules) -> None, execute(ruleset_name, facts) -> dict
```

---

## 6. 工具服务器（MCP + API + 命令）

### 6.1 MCP 服务器集成

我们的框架节点可以调用 MCP 服务器作为工具。MCP 服务器暴露能力（向量搜索、知识库查询、外部 API），节点在其权限允许列表中调用这些能力。

```yaml
# framework.yaml — MCP 工具发现
mcp_servers:
  knowledge_base:
    command: "npx @anthropic/mcp-server-knowledge-base"
    args: ["--db-path", "./kb.sqlite"]
    tools: [search_documents, get_document]
  payment_gateway:
    command: "python mcp_servers/payment_server.py"
    env:
      API_KEY: "${PAYMENT_API_KEY}"
    tools: [payment_charge, payment_refund]
  # 框架在启动时自动发现工具。
  # 可用工具：vector_search、payment_charge、payment_refund……
```

### 6.2 工具注册

通过 YAML 配置注册工具（API、MCP、命令）：

```yaml
# framework.yaml
tools:
  - name: calculate_premium_api
    type: api
    access_level: read
    api:
      method: POST
      url: "/api/v1/premium"
      timeout_ms: 5000
      request_body_schema:
        type: object
        properties:
          coverage_amount: { type: number }
          property_type: { type: string }

  - name: vector_search_mcp
    type: mcp
    access_level: read
    mcp:
      server: knowledge_base
      tool_name: search_documents

  - name: run_risk_model_cmd
    type: command
    access_level: read
    command:
      run: "python /opt/models/risk.py"
      timeout_ms: 30000
      sandbox: true

  - name: delegate_faq_to_agent
    type: a2a
    access_level: read
    a2a:
      agent_id: rag_faq
      mode: sync
      timeout_ms: 10000
      input_mapping:
        question: "{{params.question}}"
        conversation_context: "{{params.context}}"
      output_mapping:
        answer: "{{a2a_response.results.answer}}"
        sources: "{{a2a_response.results.sources}}"

  - name: opencode_review_code
    type: sdk
    access_level: read
    sdk:
      provider: opencode
      action: ask
      prompt_template: "Review the following code for security issues:\n\n{{params.code}}"
      timeout_ms: 30000
      context:
        working_directory: "/path/to/project"
```

### 6.3 Claude Desktop 集成

当框架与 Claude Desktop 一起使用时，MCP 工具会自动暴露：

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "deterministic-workflow": {
      "command": "python",
      "args": ["-m", "deterministic_workflow.mcp_server"],
      "env": {
        "WORKFLOW_CONFIG": "workflows/home_insurance_quote.yaml"
      }
    }
  }
}
```

### 6.4 工具失败路由到 `errorNode`

当工具调用失败（超时、权限拒绝、无效响应）时，框架将执行路由到配置的 `errorNode`，而不是使工作流崩溃：

```yaml
# framework.yaml
tool_failure_handling:
  default_error_node: errorNode
  timeout_ms: 30000
  max_retries: 2

nodes:
  calculate_premium:
    tools: [calculate_premium_api, run_risk_model_cmd]
    on_tool_failure:
      route_to: errorNode       # 覆盖 default_error_node
      fallback_on_timeout: true     # 超时时使用缓存/默认值
      escalate_after: 3             # 升级前的重试次数

  errorNode:
    strategies: [clarify, escalate, terminate]
    on_clarify: "询问用户缺失/更正后的输入"
    on_escalate: "携带错误上下文通知人工 Agent"
    on_terminate: "优雅地结束对话并致歉"
```

这确保了确定性行为：每个工具失败都有定义的恢复路径，并且失败可通过 LangSmith 追踪进行审计。

---

## 7. 状态机 — `transitions`

### 7.1 角色

Python `transitions` 库提供确定性 FSM 层。我们的框架从领域模型 YAML（状态 + 转换 + 守卫）生成 `transitions.Machine`，然后将其包装为 LangGraph 节点。

### 7.2 Graphviz 导出

通过 YAML 配置 FSM 可视化并导出到 Graphviz：

```yaml
# framework.yaml
fsm:
  source: "domain-models/home-insurance.yaml"
  visualization:
    format: png
    output: "docs/diagrams/home_insurance_fsm.png"
    engine: dot                    # Graphviz 布局引擎
    render_on_build: true          # 图编译时自动导出

  # 从领域模型 YAML 生成：状态、转换、守卫
  # 导出为静态 FSM 图用于文档
```

### 7.3 集成流程

```
domain-model.yaml
    │
    ▼
FSMGenerator → transitions.Machine（状态、转换、守卫）
    │
    ▼
GraphCompiler → LangGraph StateGraph（节点、条件边）
    │
    ▼
可视化：
  - transitions: graph.draw() → PNG（静态）
  - langgraph dev → 浏览器（交互式）
  - LangFlow → 拖拽式编辑器
```

---

## 8. PII 检测 — Presidio

### 8.1 角色

Microsoft Presidio 提供 PII 检测和匿名化。**权威的 PII 处理设计** — 包括后生成阶段清理、提示词过滤、审计日志脱敏以及领域模型中的 PII 规则 — 定义在 [Response Generation Layer §8 敏感字段处理](./2026-06-17-response-generation-layer-design.md)。

工具生态通过声明式配置集成 Presidio 作为 PII 检测引擎：

```yaml
# framework.yaml
pii:
  engine: presidio
  language: en
  masking_strategy: partial_mask
```

---

## 9. LLM 提供商

### 9.1 支持的提供商

| 提供商 | 包 | 用途 |
|----------|---------|-----|
| **OpenAI** | `langchain-openai` | 提取、决策、响应生成 |
| **Anthropic (Claude)** | `langchain-anthropic` | 提取、响应生成、目标设定 |
| **本地 (Ollama)** | `langchain-ollama` | 离线提取、PII 安全处理 |
| **Azure OpenAI** | `langchain-openai` | 企业部署 |

### 9.2 提供商配置

```yaml
# framework.yaml
llm:
  default_provider: openai
  providers:
    openai:
      model: gpt-4o
      temperature: 0
      max_tokens: 4096
    anthropic:
      model: claude-sonnet-4-20250514
      temperature: 0
      max_tokens: 4096

  # 按节点覆盖
  nodes:
    extract_property_info:
      provider: anthropic
      temperature: 0
    generate_quote_response:
      provider: openai
      temperature: 0.3
```

---

## 10. 完整工具集成示例

全栈配置：从 YAML → LangFlow → LangGraph → LangSmith — 全部声明式：

```yaml
# framework.yaml — 完整集成配置
engine:
  domain_model: "domain-models/home-insurance.yaml"
  workflow_config: "workflows/home_insurance_quote.yaml"
  rule_engine: durable_rules
  checkpoint_backend: "postgresql://localhost:5432/langgraph"

llm:
  default_provider: openai
  providers:
    openai: { model: gpt-4o, temperature: 0, max_tokens: 4096 }
    anthropic: { model: claude-sonnet-4-20250514, temperature: 0, max_tokens: 4096 }

langsmith:
  api_key: "${LANGSMITH_API_KEY}"
  tracing: true
  project: "home-insurance-quote"

mcp_servers:
  knowledge_base:
    command: "npx @anthropic/mcp-server-knowledge-base"
    args: ["--db-path", "./kb.sqlite"]
  payment_gateway:
    command: "python mcp_servers/payment_server.py"
    env: { API_KEY: "${PAYMENT_API_KEY}" }

tools:
  - name: calculate_premium_api
    type: api
    access_level: read
    api: { method: POST, url: "/api/v1/premium", timeout_ms: 5000 }
  - name: run_risk_model_cmd
    type: command
    access_level: read
    command: { run: "python /opt/models/risk.py", timeout_ms: 30000, sandbox: true }

tool_failure_handling:
  default_error_node: errorNode
  timeout_ms: 30000
  max_retries: 2

fsm:
  source: "domain-models/home-insurance.yaml"
  visualization: { format: png, output: "docs/diagrams/home_insurance_fsm.png" }

pii:
  engine: presidio
  language: en
  masking_strategy: partial_mask

export:
  langflow: "langflow/workflows/home_insurance.json"
  langgraph: "langgraph.json"
```

**运行时流程：**
1. 框架加载 `framework.yaml` → 自动发现所有工具、规则引擎、PII 配置
2. 从领域模型 + 工作流编译 LangGraph `StateGraph`
3. 导出为 LangFlow JSON（用于可视化编辑）和 LangGraph JSON（用于开发服务器）
4. 每次对话自动在 LangSmith Studio 中追踪
```

---

## 11. 工具决策矩阵

| 需求 | 工具 | 原因 |
|------|------|-----|
| 可视化构建工作流 | **LangFlow** | 拖拽式，导出为代码 |
| 本地开发 + 调试 | **LangGraph CLI** | 热重载，图视图，免费 |
| 生产追踪 + 评估 | **LangSmith Studio** | 时间旅行调试，评估数据集 |
| FSM 定义 | **transitions** | Python 原生，Graphviz 导出 |
| 图运行时 | **LangGraph** | 状态图，检查点，流式传输 |
| 复杂规则 | **durable_rules** | When/then 推理，类似 Drools |
| 简单规则 | **business-rules** | 零推理 YAML 规则 |
| 专家系统规则 | **pyknow** | Fact/KnowledgeEngine 模型 |
| PII 检测 | **Presidio** | 微软支持，多语言 |
| 外部工具 | **MCP 服务器** | 任意语言，标准协议 |
| Claude Desktop | **MCP 配置** | 自动将工作流暴露为工具 |

---

## 12. 开放问题

1. **LangFlow 组件应从领域模型 YAML 自动生成，还是需要手动连接？** 自动生成简化了采用门槛，但可能过度约束可视化编辑器体验。

2. **MCP 工具失败的容错边界是什么？** 当 MCP 服务器（例如支付网关）不可达时，工作流应将请求排队等待重试、回退到缓存响应，还是立即升级？

3. **如何在 LangSmith 中对评估数据集进行版本控制和回滚？** 随着领域模型演化，评估结果可能会漂移 — 我们是否应将评估数据集固定到工作流版本标签？

4. **框架是否支持非 Python 的 LangGraph 运行时？** LangGraph.js 对 TypeScript 用户已生产就绪；框架规范应仅限 Python，还是定义运行时无关的抽象层？

5. **自定义规则引擎在注册时如何验证？** YAML 配置指定了模块和类 — 框架在接受引擎之前是否应强制执行契约检查（接口合规性、冒烟测试）？

---

## 参考文献

- [高层设计](./2026-06-16-deterministic-workflow-framework-design.md) — 框架架构、权限模型
- [提取层](./2026-06-17-extraction-layer-design.md) — 验证节点中的规则引擎集成
- [路由与执行](./2026-06-17-routing-execution-layer-design.md) — 决策节点中的规则引擎、工具系统
- [响应生成](./2026-06-17-response-generation-layer-design.md) — PII 清理、Widget 渲染
- [LangFlow](https://github.com/langflow-ai/langflow) — 可视化编辑器（150k stars，MIT）
- [LangGraph CLI](https://pypi.org/project/langgraph-cli/) — 开发服务器 + 图可视化
- [LangSmith Studio](https://docs.langchain.com/langsmith/studio) — 调试 + 监控 IDE
- [transitions](https://github.com/pytransitions/transitions) — Python 状态机库
- [durable_rules](https://github.com/jruizgit/rules) — Python 正向链规则引擎
- [Presidio](https://github.com/microsoft/presidio) — 微软 PII 检测
