# Deterministic Workflow Framework — High-Level Design / 确定性工作流框架 — 高层设计

**设计范围：** 仅架构讨论，不涉及实现代码。

---

## Changelog / 变更日志

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-16 | 0.1.0 | 初始三层架构 |
| 2026-06-16 | 0.2.0 | 重置为最小版本，以便逐步讨论 |
| 2026-06-16 | 0.3.0 | 添加状态机设计交叉引用；将附录翻译为英文 |
| 2026-06-16 | 0.4.0 | 添加示例参考；将所有示例统一到家庭保险领域 |
| 2026-06-17 | 0.5.0 | 添加框架设计原则（代码规范、JSON 护栏、权限模型） |
| 2026-06-17 | 0.6.0 | 术语一致性：errorNode、阶段感知路由；添加 YAML schema 概览；标记已解决的开放问题 |
| 2026-06-17 | 0.7.0 | 添加上下文水合层：预处理步骤在三层执行前加载历史、状态、会话、外部实体数据 |
| 2026-06-18 | 0.8.0 | 更新相关设计文档，包含所有子规范 |
| 2026-06-18 | 0.9.0 | 更新 `ToolMeta.type` 枚举：从 `api\|mcp\|command\|llm` 扩展为 `api\|mcp\|command\|llm\|a2a\|sdk`（Decision 24）；更新文档树 |

---

## 1. 问题陈述

受监管行业（金融、医疗、保险）中的企业聊天机器人需要可审计、可预测——但用户使用自然语言交流。纯规则系统无法理解用户；纯 LLM 驱动系统无法保证正确性。

## 2. 核心架构：上下文水合 + 三层架构

每个工作流交互始于一个**上下文水合**步骤，加载当前业务状态所需的最新数据。它**不是**盲目调用所有 API — 而是有选择地刷新 `AgentState` 中当前任务真正需要的数据。

```
用户输入
   |
   v
+-----------------------+
| 上下文水合              |  -> "当前任务需要什么数据？"
| 有选择地刷新            |     只加载业务相关数据：
| AgentState 数据         |     例如保险申请表数据，
+-----------+-----------+     用于确定下一步任务
            v
+-----------------------+
| 第一层：理解 (UNDERSTAND)   |  -> "用户想要什么？"
| 意图 + 实体              |
+-----------+-----------+
            v
+-----------------------+
| 第二层：决策 (DECIDE)       |  -> "我们应该做什么？"
| 路由 + 执行               |
+-----------+-----------+
            v
+-----------------------+
| 第三层：响应 (RESPOND)      |  -> "我们该怎么回复？"
| 消息生成                 |
+-----------------------+
```

- **上下文水合** 有选择地加载当前业务任务所需的最新数据 — 刷新 `AgentState` 中当前的申请表数据、理赔状态或支付历史 — 以便框架准确知道下一步做什么。它**不会**加载无关的 CRM 实体或穷举所有 API。
- **第一层** 从自由形式的用户输入中提取意图和结构化实体。
- **第二层** 决定下一个状态，验证数据，并执行确定性业务逻辑。
- **第三层** 生成用户可见的响应。

### 2.1 YAML Schema 概览（上下文水合 + 三层架构）

```yaml
workflow:
  context_hydration:
    always_load:           # 每轮交互都刷新
      - source: checkpoint_db
        fields: [conversation_history, persisted_agentState]
      - source: session_store
        fields: [user_profile, oauth_scopes]
    on_phase_entry:        # 进入此阶段时刷新
      collect_property_info:
        - source: application_service   # 加载当前申请表
          fields: [property_type, address, building_age, floor_area]
      process_payment:
        - source: payment_gateway
          fields: [outstanding_balance, payment_methods]
  layers:
    understand:
      nodes: [classify_intent, extract_entities]
    decide:
      nodes: [route, validate, execute, fallback]
    respond:
      nodes: [generate_response]
  mode: deterministic
```

### 2.2 上下文水合 — 工作机制

上下文水合是**有选择性的** — 只刷新当前业务任务依赖的数据。框架根据当前 `agentState.phase` 和领域模型中的实体绑定决定加载什么。

**示例（保险报价）：**

```
agentState.phase = "collect_coverage_needs"
    → 领域模型状态绑定实体："property_info"
    → 加载 property_info 的当前申请表数据
    → 检测到：property_type = "house", building_age = 5, address = null
    → 确定下一步任务：询问地址
```

**不加载：** CRM 历史、支付数据、理赔记录 — 与报价任务无关。只刷新当前阶段的申请表字段。

**水合来源：**

| 来源 | 何时加载 | 水合内容 |
|------|----------|----------|
| **Checkpoint DB** | 每轮交互 | 对话历史 + 持久化的 AgentState |
| **Session Store** | 每轮交互 | 用户资料、OAuth 权限范围 |
| **Domain Entity API** | 进入阶段时 | 绑定实体的当前数据（如申请表状态） |
| **External Business API** | 按需 | 仅当节点的代码执行器声明依赖时（如 process_payment 状态中的 payment_gateway） |

## 3. 核心洞察：逐节点控制，而非逐层控制

LLM/确定性的决策不是在层级层面做出的。每一层中的每个独立节点自行选择使用 LLM 还是确定性规则。

例如，在第二层中，路由节点可能是一个纯粹的 `switch` 语句（确定性），而它旁边的节点可能使用 LLM 进行语义验证（LLM）。层级描述的是**做什么**（*what*）；节点描述的是**怎么做**（*how*）。

## 4. 框架设计原则

### 4.1 框架即接口 + 模式注入

框架为开发者暴露清晰的接口以实现业务逻辑。内部则注入经过验证的模式来处理"脏活累活"——让开发者专注于业务逻辑，而非基础设施：

| 框架关注点 | 注入的模式 |
|-------------------|-------------------|
| LLM 护栏 | JSON schema 验证、字段存在性检查、类型强制转换 |
| 权限执行 | 逐节点工具白名单 + 转换白名单 |
| 重试预算 | 逐节点重试次数 + errorNode 统一处理 |
| 审计追踪 | 每个决策、提取和转换都记录日志 |
| 确定性回退 | 每个可提取字段的正则/关键词回退 |
| 状态感知 | 当前 FSM 状态注入到每个 LLM prompt 中 |
| 阶段感知路由 + 返回栈 |
| 子工作流复用 | 共享能力定义一次，可从任意状态调用 |

所有 LLM 交互均产出结构化 JSON 输出，并由框架强制执行的护栏进行验证（schema 检查、字段存在性检查、类型强制转换）。自由文本生成仅限于第三层。

**接口哲学：** 开发者实现 `ExtractionNode.execute()`、`ValidatorNode.validate()`、`TransformNode.transform()` 等方法。框架处理围绕它们的一切。

### 4.2 代码规范

- 每个方法 ≤ **50 行**
- 每个文件 ≤ **1000 行**
- 执行器小巧、可组合、单一职责
- 复杂子工作流拆分到多个文件和子工作流中
- 可复用的逻辑提取到共享模块中

### 4.3 LLM 输出必须是 JSON——始终如此

所有 LLM 交互均产出**结构化 JSON 输出**。框架强制执行输出验证护栏：

1. **Schema 检查** — 输出必须匹配声明的 JSON schema
2. **字段存在性** — 必填字段必须存在且非空
3. **类型强制转换** — schema 期望 `int` 时，`"123"` → `123`
4. **违规重试** — 无效输出自动重试（在重试预算范围内）

自由文本生成仅限于**第三层（响应）**。第一层和第二层的 LLM 输出始终是结构化 JSON。

### 4.4 权限模型（概览）

每个节点都有一个权限集，定义其可以访问的内容：

```
NodePermission {
  allowed_tools:      string[]    // 此节点可以调用哪些工具
  allowed_transitions: string[]   // 此节点可以转换到哪些节点
  max_retries:        int         // 此节点的重试预算
}
```

工具按元数据进行分类：

```
ToolMeta {
  name:        string
  type:        "api" | "mcp" | "command" | "llm" | "a2a" | "sdk"
  access_level: "read" | "write" | "sensitive_data_read" | "dangerous_operation_write"
  execute():   Result        // 工具执行方法
}
```

权限执行发生在两个层面：

1. **配置级别** — 在工作流 YAML 中静态声明（节点/工具白名单）
2. **OAuth / 基于角色** — 运行时根据已认证用户的角色进行动态执行

详细的权限设计见 [路由与执行层](./2026-06-17-routing-execution-layer-design.md)。

## 5. 相关设计文档

- **[状态机设计](./2026-06-16-state-machine-design.md)** — 详细的 FSM 层设计：转换 + LangGraph 融合、状态元数据（前置条件、守卫、不变式）、意图+状态解析，以及 FSM 特定的开放问题。
- **[意图分类设计](./2026-06-16-intent-classification-design.md)** — 第一层意图分类策略：LLM 优先 + 关键词回退、输出契约、对话上下文。
- **[提取层设计](./2026-06-17-extraction-layer-design.md)** — 第一层实体提取：提取/验证/转换流水线，多种实现方案。
- **[领域模型设计](./2026-06-17-domain-model-design.md)** — 单一事实来源：实体 + 状态 + 转换 schema，跨工作流复用。
- **[路由与执行层设计](./2026-06-17-routing-execution-layer-design.md)** — 第二层路由与执行：业务逻辑、决策节点、阶段感知路由、重试预算、子工作流复用、权限模型。
- **[家庭保险示例](../examples/home-insurance/)** — 完整的工作流定义（`workflow.yaml`）、意图目录、端到端场景和审计日志示例。

## 6. 下游：技能辅助的规范生成

本规范文档集具有双重用途：

1. **框架设计参考** — 记录确定性工作流架构和设计决策
2. **访谈模板** — 下游技能加载这些规范，通过引导式问答帮助开发者生成完整的、针对特定产品的确定性 AI Agent 规范，为代码实现规划做好准备

```
开发者描述其产品（例如，"保险理赔聊天机器人"）
    → 技能加载框架规范作为访谈模板
    → 技能逐规范地提出产品特定的问题
    → 技能输出完整的、针对特定产品的规范
    → 开发者进入实现规划阶段
```

框架规范的设计具有清晰的决策边界：**"框架决策"**（跨所有产品复用）vs.**"用户决策"**（由技能针对每个产品提出）。访谈流程将在所有规范文档完成后正式确定。

---

## 7. 参考文献

1. LangGraph — 状态图执行框架（运行时底层）。*github.com/langchain-ai/langgraph*
2. Rasa CALM — "LLM 理解；代码执行。" *rasa.com*
3. zelkim/langgraph-insurance-chatbot — LangGraph.js 保险报价聊天机器人。*github.com/zelkim/langgraph-insurance-chatbot*
4. Prodigal Payment Collection Agent — Python FSM 支付催收 Agent。*github.com/AvnishChitrigi/Prodigal-Assignment-Production-Ready-Payment-Collection-AI-Agent*

---

## 附录：实现规划 — 开放问题（非状态机相关）

> 设计过程中识别但推迟到实现规划阶段的问题。
> 状态机相关问题见 [状态机设计](./2026-06-16-state-machine-design.md) 附录 C。

### A.1 LLM 集成

| # | 问题 | 影响 |
|---|----------|--------|
| 1 | LLM 节点错误处理 — 超时、幻觉、工具调用失败的恢复策略 | 对话连续性 |
| 2 | LLM 节点测试 — 如何在不调用真实 LLM 的情况下验证行为 | 测试稳定性、CI 速度 |
| 3 | LLM 范围执行 — 如何确保 LLM 只处理第一层（理解）和第三层（响应），而不处理第二层（决策） | 已由决策 5 解决：逐节点粒度，而非逐层执行 |
| 4 | 上下文过滤 — 可以传递给 LLM 的数据，敏感字段脱敏规则 | PII/GDPR 合规 |

### A.2 安全与合规

| # | 问题 | 影响 |
|---|----------|--------|
| 5 | 工具权限 — 谁可以在哪个状态下调用哪个工具，白名单粒度和管理 | 防止 LLM 越权 |
| 6 | PII 处理 — 标记化、传输加密、存储策略 | PCI DSS / SOC2 / GDPR |

### A.3 人机协作 (Human-in-the-Loop)

| # | 问题 | 影响 |
|---|----------|--------|
| 7 | 审批 UI 设计 — 审批者看到什么，是否可以修改数据 | 审批有效性 |
| 8 | 审批超时 — 审批者不可用时自动批准、拒绝或委托 | 业务连续性 |
| 9 | 审批委托链 — 向谁升级以及升级顺序 | 组织适配 |

### A.4 测试与质量

| # | 问题 | 影响 |
|---|----------|--------|
| 10 | 确定性节点（代码执行器）单元测试策略 | 核心业务逻辑正确性 |
| 11 | 生成的图集成测试 — 如何验证自动生成的 LangGraph 行为 | 端到端正确性 |

### A.5 部署与运维

| # | 问题 | 影响 |
|---|----------|--------|
| 12 | 蓝绿部署 — 新旧工作流并存时的对话路由 | 零停机更新 |
| 13 | 多租户隔离 — 如何在客户之间隔离工作流实例 | 安全性、资源管理 |
| 14 | 审计日志存储 — 格式、保留期限、查询 API | 监管合规审查 |
